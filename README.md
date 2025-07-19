# 🔧 Qualtrics Troubleshooter

An AI-powered RAG (Retrieval-Augmented Generation) application that helps non-technical staff troubleshoot Qualtrics surveys through intelligent chat assistance.

## ✨ Features

- **Document Processing**: Upload .docx manuals with automatic text chunking and image extraction
- **Vector Search**: ChromaDB-powered semantic search with BM25 keyword fallback
- **Streaming Chat**: Real-time AI responses powered by OpenAI GPT-4o
- **Image Support**: Display screenshots from documents in chat responses
- **Session Management**: Multiple chat sessions with message history
- **Auto-Reindexing**: File watcher automatically processes updated documents
- **Beautiful UI**: Dark/light mode, responsive design, typing indicators

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- MongoDB (local or remote)
- OpenAI API key

### Installation

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd qualtrics-troubleshooter
   ```

2. **Set up environment variables**
   ```bash
   cp backend/.env.example backend/.env
   ```
   
   Edit `backend/.env` and add your OpenAI API key:
   ```env
   OPENAI_API_KEY="your-actual-openai-api-key-here"
   ```

3. **Install backend dependencies**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

4. **Install frontend dependencies**
   ```bash
   cd ../frontend
   yarn install
   ```

5. **Start MongoDB** (if running locally)
   ```bash
   mongod
   ```

6. **Run the application**
   ```bash
   # Terminal 1 - Backend
   cd backend
   uvicorn server:app --reload --host 0.0.0.0 --port 8001
   
   # Terminal 2 - Frontend
   cd frontend
   yarn start
   ```

7. **Access the application**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8001

## 📖 Usage

1. **Upload Documents**: Use the "Upload Manual" button to upload .docx files
2. **Ask Questions**: Type troubleshooting questions in the chat interface
3. **Get AI Responses**: Receive contextual answers with relevant document sections
4. **View Images**: Click on image thumbnails to view full screenshots
5. **Manage Sessions**: Create multiple chat sessions for different topics

## 🏗️ Architecture

- **Backend**: FastAPI with WebSocket support
- **Frontend**: React with real-time chat interface
- **Database**: MongoDB for sessions/messages, ChromaDB for vectors
- **AI**: OpenAI GPT-4o for chat, text-embedding-3-small for vectors
- **Document Processing**: python-docx for .docx parsing
- **Search**: Hybrid vector similarity + BM25 keyword search

## 📁 Project Structure

```
qualtrics-troubleshooter/
├── backend/
│   ├── server.py           # Main FastAPI application
│   ├── requirements.txt    # Python dependencies
│   └── .env.example       # Environment template
├── frontend/
│   ├── src/
│   │   ├── App.js         # Main React component
│   │   ├── App.css        # Styling
│   │   └── index.js       # Entry point
│   └── package.json       # Node dependencies
└── data/
    ├── manual/            # Uploaded .docx files
    ├── images/            # Extracted images
    └── chroma/            # Vector database
```

## 🔑 API Endpoints

- `POST /api/chat/sessions` - Create new chat session
- `GET /api/chat/sessions` - List all sessions
- `GET /api/chat/sessions/{id}/messages` - Get session messages
- `POST /api/ingest/upload` - Upload document for processing
- `POST /api/ingest/reindex` - Manually reindex all documents
- `WebSocket /api/chat/{session_id}` - Streaming chat endpoint

## ⚙️ Configuration

### Environment Variables

- `OPENAI_API_KEY` - Your OpenAI API key (required)
- `MONGO_URL` - MongoDB connection string
- `DB_NAME` - MongoDB database name
- `DATA_DIR` - Directory for storing data files

### Document Processing

- **Chunk Size**: 500 tokens with 50-token overlap
- **Supported Formats**: .docx files
- **Image Extraction**: Automatic base64 encoding
- **Vector Model**: text-embedding-3-small

## 🔒 Security

- Environment variables for sensitive data
- No API keys stored in code
- Local processing for document content
- MongoDB for persistent storage

## 🛠️ Development

### Running Tests

```bash
# Backend tests
cd backend
python -m pytest

# Frontend tests
cd frontend
yarn test
```

### Code Structure

- **Document Processing**: Handles .docx parsing, text chunking, image extraction
- **Vector Database**: ChromaDB with SQLite persistence
- **RAG Engine**: Hybrid search with context assembly
- **WebSocket Handler**: Real-time streaming chat
- **React Frontend**: Modern UI with WebSocket client

## 📝 License

MIT License - feel free to use this project for your organization's Qualtrics troubleshooting needs!

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

---

Built with ❤️ for better Qualtrics support experiences
