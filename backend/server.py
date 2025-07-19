import os
import asyncio
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

import openai
import chromadb
from chromadb.config import Settings
import tiktoken
from docx import Document
from docx.shared import Inches
import base64
from io import BytesIO
from rank_bm25 import BM25Okapi
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Environment variables
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
DATA_DIR = Path(os.environ.get('DATA_DIR', '/app/data'))
MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']

# Setup directories
MANUAL_DIR = DATA_DIR / 'manual'
IMAGES_DIR = DATA_DIR / 'images'
CHROMA_DIR = DATA_DIR / 'chroma'

for dir_path in [MANUAL_DIR, IMAGES_DIR, CHROMA_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Initialize OpenAI client
openai.api_key = OPENAI_API_KEY

# Initialize ChromaDB
chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
collection = chroma_client.get_or_create_collection(
    name="qualtrics_manual",
    metadata={"hnsw:space": "cosine"}
)

# Initialize tokenizer for chunking
encoding = tiktoken.encoding_for_model("gpt-4")

# MongoDB connection
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client[DB_NAME]

# FastAPI app setup
app = FastAPI(title="Qualtrics Troubleshooter")
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Models
class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    chunks_used: Optional[List[str]] = None

class ChatSession(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    title: str = "New Chat"

class DocumentProcessor:
    def __init__(self):
        self.chunk_size = 500
        self.chunk_overlap = 50
    
    def extract_text_and_images(self, docx_path: Path) -> Dict[str, Any]:
        """Extract text, headings, and images from Word document"""
        doc = Document(docx_path)
        extracted_data = {
            'text_chunks': [],
            'images': [],
            'metadata': []
        }
        
        current_heading_path = []
        current_text = ""
        current_images = []
        
        for element in doc.element.body:
            if element.tag.endswith('p'):  # Paragraph
                para = None
                for p in doc.paragraphs:
                    if p._element == element:
                        para = p
                        break
                
                if para:
                    # Check if it's a heading
                    if para.style.name.startswith('Heading'):
                        # Save previous section if exists
                        if current_text.strip():
                            extracted_data['text_chunks'].append(current_text.strip())
                            extracted_data['metadata'].append({
                                'heading_path': current_heading_path.copy(),
                                'images': current_images.copy()
                            })
                        
                        # Update heading path
                        heading_level = int(para.style.name.split()[-1]) if para.style.name.split()[-1].isdigit() else 1
                        current_heading_path = current_heading_path[:heading_level-1]
                        current_heading_path.append(para.text.strip())
                        current_text = ""
                        current_images = []
                    else:
                        current_text += para.text + "\n"
                        
                        # Extract images from this paragraph
                        for run in para.runs:
                            for inline in run._element.xpath('.//a:blip'):
                                try:
                                    image_part = doc.part.related_parts[inline.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')]
                                    image_data = image_part.blob
                                    image_b64 = base64.b64encode(image_data).decode('utf-8')
                                    image_id = f"img_{len(extracted_data['images'])}.png"
                                    
                                    extracted_data['images'].append({
                                        'id': image_id,
                                        'data': image_b64,
                                        'format': 'png'
                                    })
                                    current_images.append(image_id)
                                except Exception as e:
                                    logger.warning(f"Could not extract image: {e}")
        
        # Save final section
        if current_text.strip():
            extracted_data['text_chunks'].append(current_text.strip())
            extracted_data['metadata'].append({
                'heading_path': current_heading_path.copy(),
                'images': current_images.copy()
            })
        
        return extracted_data
    
    def chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks"""
        tokens = encoding.encode(text)
        chunks = []
        
        for i in range(0, len(tokens), self.chunk_size - self.chunk_overlap):
            chunk_tokens = tokens[i:i + self.chunk_size]
            chunk_text = encoding.decode(chunk_tokens)
            chunks.append(chunk_text)
            
        return chunks
    
    async def process_document(self, docx_path: Path) -> bool:
        """Process a document and store in vector database"""
        try:
            logger.info(f"Processing document: {docx_path}")
            
            # Extract text and images
            extracted = self.extract_text_and_images(docx_path)
            
            # Store images in database
            for image in extracted['images']:
                await db.images.replace_one(
                    {'id': image['id']},
                    image,
                    upsert=True
                )
            
            # Remove existing chunks for this document
            existing_chunks = collection.get(where={"source_doc": str(docx_path.name)})
            if existing_chunks['ids']:
                collection.delete(ids=existing_chunks['ids'])
            
            # Process each text chunk
            all_chunks = []
            all_metadatas = []
            all_ids = []
            
            for i, (text_chunk, metadata) in enumerate(zip(extracted['text_chunks'], extracted['metadata'])):
                # Split into smaller chunks if needed
                sub_chunks = self.chunk_text(text_chunk)
                
                for j, sub_chunk in enumerate(sub_chunks):
                    chunk_id = f"{docx_path.stem}_{i}_{j}"
                    
                    # Generate embedding
                    response = await asyncio.to_thread(
                        openai.embeddings.create,
                        model="text-embedding-3-small",
                        input=sub_chunk
                    )
                    embedding = response.data[0].embedding
                    
                    chunk_metadata = {
                        "chunk_id": chunk_id,
                        "heading_path": " > ".join(metadata['heading_path']) if metadata['heading_path'] else "",
                        "source_doc": docx_path.name,
                        "image_refs": ",".join(metadata['images']) if metadata['images'] else "",
                        "page_num": i + 1,
                        "text": sub_chunk
                    }
                    
                    all_chunks.append(sub_chunk)
                    all_metadatas.append(chunk_metadata)
                    all_ids.append(chunk_id)
            
            # Generate embeddings for all chunks
            if all_chunks:
                response = await asyncio.to_thread(
                    openai.embeddings.create,
                    model="text-embedding-3-small",
                    input=all_chunks
                )
                embeddings = [data.embedding for data in response.data]
                
                # Store in ChromaDB
                collection.add(
                    documents=all_chunks,
                    metadatas=all_metadatas,
                    ids=all_ids,
                    embeddings=embeddings
                )
            
            logger.info(f"Successfully processed {len(all_chunks)} chunks from {docx_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing document {docx_path}: {e}")
            return False

# Initialize document processor
doc_processor = DocumentProcessor()

class DocumentWatcher(FileSystemEventHandler):
    def __init__(self):
        self.loop = None
    
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.docx'):
            logger.info(f"Document modified: {event.src_path}")
            if self.loop:
                asyncio.run_coroutine_threadsafe(
                    doc_processor.process_document(Path(event.src_path)),
                    self.loop
                )
    
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.docx'):
            logger.info(f"Document created: {event.src_path}")
            if self.loop:
                asyncio.run_coroutine_threadsafe(
                    doc_processor.process_document(Path(event.src_path)),
                    self.loop
                )

# Start document watcher
document_watcher = DocumentWatcher()
observer = Observer()
observer.schedule(document_watcher, str(MANUAL_DIR), recursive=False)

class RAGQueryEngine:
    def __init__(self):
        self.bm25 = None
        self.documents = []
        self.metadatas = []
        self._update_bm25()
    
    def _update_bm25(self):
        """Update BM25 index with current documents"""
        try:
            results = collection.get()
            if results['documents']:
                self.documents = results['documents']
                self.metadatas = results['metadatas']
                tokenized_docs = [doc.lower().split() for doc in self.documents]
                self.bm25 = BM25Okapi(tokenized_docs)
        except Exception as e:
            logger.error(f"Error updating BM25: {e}")
    
    async def search(self, query: str, k: int = 8) -> List[Dict[str, Any]]:
        """Perform hybrid search (vector + BM25)"""
        try:
            # Vector similarity search
            response = await asyncio.to_thread(
                openai.embeddings.create,
                model="text-embedding-3-small",
                input=query
            )
            query_embedding = response.data[0].embedding
            
            vector_results = collection.query(
                query_embeddings=[query_embedding],
                n_results=k
            )
            
            results = []
            if vector_results['documents'] and vector_results['documents'][0]:
                for i, doc in enumerate(vector_results['documents'][0]):
                    metadata = vector_results['metadatas'][0][i]
                    distance = vector_results['distances'][0][i]
                    
                    # Get associated images
                    images = []
                    if metadata.get('image_refs'):
                        img_ids = metadata['image_refs'].split(',') if metadata['image_refs'] else []
                        for img_id in img_ids:
                            if img_id.strip():
                                img_doc = await db.images.find_one({'id': img_id.strip()})
                                if img_doc:
                                    images.append(img_doc)
                    
                    results.append({
                        'text': doc,
                        'metadata': metadata,
                        'distance': distance,
                        'images': images,
                        'source': 'vector'
                    })
            
            # BM25 keyword search as fallback
            if self.bm25 and (not results or min(r['distance'] for r in results) > 0.7):
                query_tokens = query.lower().split()
                bm25_scores = self.bm25.get_scores(query_tokens)
                top_bm25_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:k//2]
                
                for idx in top_bm25_indices:
                    if idx < len(self.documents) and bm25_scores[idx] > 0:
                        metadata = self.metadatas[idx]
                        
                        # Get associated images
                        images = []
                        if metadata.get('image_refs'):
                            for img_id in metadata['image_refs']:
                                img_doc = await db.images.find_one({'id': img_id})
                                if img_doc:
                                    images.append(img_doc)
                        
                        results.append({
                            'text': self.documents[idx],
                            'metadata': metadata,
                            'distance': 1 - bm25_scores[idx],
                            'images': images,
                            'source': 'bm25'
                        })
            
            # Sort by relevance and remove duplicates
            seen_texts = set()
            unique_results = []
            for result in sorted(results, key=lambda x: x['distance']):
                if result['text'] not in seen_texts:
                    seen_texts.add(result['text'])
                    unique_results.append(result)
            
            return unique_results[:k]
            
        except Exception as e:
            logger.error(f"Error in search: {e}")
            return []

# Initialize RAG engine
rag_engine = RAGQueryEngine()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
    
    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]

manager = ConnectionManager()

# API Routes
@api_router.post("/chat/sessions")
async def create_chat_session():
    """Create a new chat session"""
    session = ChatSession()
    await db.chat_sessions.insert_one(session.dict())
    return session

@api_router.get("/chat/sessions")
async def get_chat_sessions():
    """Get all chat sessions"""
    sessions = await db.chat_sessions.find().sort("created_at", -1).to_list(100)
    return [ChatSession(**session) for session in sessions]

@api_router.get("/chat/sessions/{session_id}/messages")
async def get_chat_messages(session_id: str):
    """Get messages for a chat session"""
    messages = await db.chat_messages.find({"session_id": session_id}).sort("timestamp", 1).to_list(1000)
    return [ChatMessage(**message) for message in messages]

@api_router.post("/ingest/reindex")
async def reindex_documents():
    """Manually trigger document reindexing"""
    try:
        processed_count = 0
        for docx_file in MANUAL_DIR.glob("*.docx"):
            success = await doc_processor.process_document(docx_file)
            if success:
                processed_count += 1
        
        # Update BM25 index
        rag_engine._update_bm25()
        
        return {"message": f"Successfully reindexed {processed_count} documents"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/ingest/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload a document for processing"""
    if not file.filename.endswith('.docx'):
        raise HTTPException(status_code=400, detail="Only .docx files are supported")
    
    try:
        # Save uploaded file
        file_path = MANUAL_DIR / file.filename
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # Process the document
        success = await doc_processor.process_document(file_path)
        if success:
            rag_engine._update_bm25()
            return {"message": f"Successfully processed {file.filename}"}
        else:
            raise HTTPException(status_code=500, detail="Failed to process document")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.websocket("/chat/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for streaming chat"""
    await manager.connect(websocket, session_id)
    document_watcher.loop = asyncio.get_event_loop()
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            if message_data.get('type') == 'user_message':
                question = message_data.get('content', '')
                
                # Save user message
                user_message = ChatMessage(
                    session_id=session_id,
                    role='user',
                    content=question
                )
                await db.chat_messages.insert_one(user_message.dict())
                
                # Search for relevant chunks
                search_results = await rag_engine.search(question)
                
                if not search_results:
                    # No relevant context found
                    response_content = "I don't have enough information in the manual to answer your question. Please make sure the relevant documentation has been uploaded and indexed."
                    
                    assistant_message = ChatMessage(
                        session_id=session_id,
                        role='assistant',
                        content=response_content
                    )
                    await db.chat_messages.insert_one(assistant_message.dict())
                    
                    await websocket.send_text(json.dumps({
                        'type': 'assistant_message',
                        'content': response_content,
                        'done': True
                    }))
                    continue
                
                # Build context from search results
                context_parts = []
                images_in_response = []
                chunk_ids = []
                
                for i, result in enumerate(search_results[:5]):  # Use top 5 results
                    heading_path = " > ".join(result['metadata'].get('heading_path', []))
                    context_parts.append(f"Section: {heading_path}\nContent: {result['text']}")
                    chunk_ids.append(result['metadata'].get('chunk_id'))
                    
                    # Collect images
                    for image in result['images']:
                        if image not in images_in_response:
                            images_in_response.append(image)
                
                context = "\n\n".join(context_parts)
                
                # Create prompt
                system_prompt = """You are a friendly, professional Qualtrics troubleshooting assistant. Your role is to help users diagnose and fix issues with Qualtrics surveys.

IMPORTANT GUIDELINES:
- ALWAYS answer with numbered steps followed by bullet tips
- Be specific and actionable in your instructions
- When context includes images, reference them in your response like this: ![Image](image_id)
- If confidence is low, ask for clarification
- Focus on practical solutions
- Use plain English, avoid jargon
- Be encouraging and supportive

Format your response as:
1. Step one description
   • Tip or additional detail
   • Another helpful tip

2. Step two description
   • Relevant tip
   
Continue with more steps as needed."""

                user_prompt = f"""Question: {question}

Context from Qualtrics Manual:
{context}

Please provide a step-by-step solution to help with this Qualtrics issue."""

                # Stream response from OpenAI
                try:
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]
                    
                    stream = await asyncio.to_thread(
                        openai.chat.completions.create,
                        model="gpt-4o",
                        messages=messages,
                        stream=True,
                        max_tokens=2000,
                        temperature=0.7
                    )
                    
                    full_response = ""
                    async for chunk in stream:
                        if chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            full_response += content
                            
                            await websocket.send_text(json.dumps({
                                'type': 'assistant_message_chunk',
                                'content': content
                            }))
                    
                    # Send images after text
                    if images_in_response:
                        await websocket.send_text(json.dumps({
                            'type': 'images',
                            'images': images_in_response
                        }))
                    
                    # Send completion signal
                    await websocket.send_text(json.dumps({
                        'type': 'assistant_message',
                        'content': full_response,
                        'done': True,
                        'images': images_in_response
                    }))
                    
                    # Save assistant message
                    assistant_message = ChatMessage(
                        session_id=session_id,
                        role='assistant',
                        content=full_response,
                        chunks_used=chunk_ids
                    )
                    await db.chat_messages.insert_one(assistant_message.dict())
                    
                except Exception as e:
                    logger.error(f"Error generating response: {e}")
                    error_message = "I'm sorry, but I encountered an error while generating a response. Please try again."
                    
                    await websocket.send_text(json.dumps({
                        'type': 'assistant_message',
                        'content': error_message,
                        'done': True,
                        'error': True
                    }))
    
    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(session_id)

# Include router
app.include_router(api_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Start document watcher on startup"""
    observer.start()
    logger.info("Qualtrics Troubleshooter started")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    observer.stop()
    observer.join()
    mongo_client.close()
    logger.info("Qualtrics Troubleshooter shutdown")