#!/usr/bin/env python3
"""
Test ChromaDB directly to see if there are existing embeddings
"""

import chromadb
from pathlib import Path

# Initialize ChromaDB
CHROMA_DIR = Path("/app/data/chroma")
chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))

try:
    collection = chroma_client.get_collection("qualtrics_manual")
    
    # Get all documents
    results = collection.get()
    
    print(f"ChromaDB Collection Status:")
    print(f"Total documents: {len(results['documents']) if results['documents'] else 0}")
    print(f"Total IDs: {len(results['ids']) if results['ids'] else 0}")
    
    if results['documents'] and len(results['documents']) > 0:
        print(f"Sample document preview: {results['documents'][0][:200]}...")
        print(f"Sample metadata: {results['metadatas'][0] if results['metadatas'] else 'No metadata'}")
        print("✅ ChromaDB has existing data")
    else:
        print("❌ ChromaDB is empty")
        
except Exception as e:
    print(f"❌ Error accessing ChromaDB: {e}")