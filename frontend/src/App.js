import React, { useState, useEffect, useRef } from 'react';
import './App.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';

function App() {
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [chatSessions, setChatSessions] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [darkMode, setDarkMode] = useState(true);
  const [expandedImage, setExpandedImage] = useState(null);
  
  const websocketRef = useRef(null);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  // Auto-scroll to bottom
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Load chat sessions on mount
  useEffect(() => {
    loadChatSessions();
  }, []);

  const loadChatSessions = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/chat/sessions`);
      const sessions = await response.json();
      setChatSessions(sessions);
      
      if (sessions.length > 0 && !currentSessionId) {
        setCurrentSessionId(sessions[0].id);
        loadChatMessages(sessions[0].id);
      }
    } catch (error) {
      console.error('Error loading chat sessions:', error);
    }
  };

  const loadChatMessages = async (sessionId) => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/chat/sessions/${sessionId}/messages`);
      const messages = await response.json();
      setMessages(messages);
    } catch (error) {
      console.error('Error loading chat messages:', error);
    }
  };

  const createNewSession = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/chat/sessions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        }
      });
      const newSession = await response.json();
      
      setChatSessions(prev => [newSession, ...prev]);
      setCurrentSessionId(newSession.id);
      setMessages([]);
      
      // Disconnect existing websocket
      if (websocketRef.current) {
        websocketRef.current.close();
      }
      
      connectWebSocket(newSession.id);
    } catch (error) {
      console.error('Error creating new session:', error);
    }
  };

  const connectWebSocket = (sessionId) => {
    if (websocketRef.current) {
      websocketRef.current.close();
    }

    const wsUrl = `${BACKEND_URL.replace('http', 'ws')}/api/chat/${sessionId}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('WebSocket connected');
      setIsConnected(true);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'assistant_message_chunk') {
        setMessages(prev => {
          const newMessages = [...prev];
          const lastMessage = newMessages[newMessages.length - 1];
          
          if (lastMessage && lastMessage.role === 'assistant' && lastMessage.isStreaming) {
            lastMessage.content += data.content;
          } else {
            newMessages.push({
              id: `temp_${Date.now()}`,
              role: 'assistant',
              content: data.content,
              timestamp: new Date().toISOString(),
              isStreaming: true
            });
          }
          
          return newMessages;
        });
      } else if (data.type === 'assistant_message') {
        setIsTyping(false);
        setMessages(prev => {
          const newMessages = [...prev];
          const lastMessage = newMessages[newMessages.length - 1];
          
          if (lastMessage && lastMessage.role === 'assistant' && lastMessage.isStreaming) {
            lastMessage.content = data.content;
            lastMessage.isStreaming = false;
            lastMessage.images = data.images || [];
          }
          
          return newMessages;
        });
      } else if (data.type === 'images') {
        setMessages(prev => {
          const newMessages = [...prev];
          const lastMessage = newMessages[newMessages.length - 1];
          
          if (lastMessage && lastMessage.role === 'assistant') {
            lastMessage.images = data.images;
          }
          
          return newMessages;
        });
      }
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected');
      setIsConnected(false);
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setIsConnected(false);
    };

    websocketRef.current = ws;
  };

  const sendMessage = () => {
    if (!inputMessage.trim() || !isConnected || isTyping) return;

    const userMessage = {
      id: `user_${Date.now()}`,
      role: 'user',
      content: inputMessage.trim(),
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, userMessage]);
    setIsTyping(true);

    websocketRef.current.send(JSON.stringify({
      type: 'user_message',
      content: inputMessage.trim()
    }));

    setInputMessage('');
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleFileUpload = async () => {
    if (!selectedFile) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const response = await fetch(`${BACKEND_URL}/api/ingest/upload`, {
        method: 'POST',
        body: formData
      });

      if (response.ok) {
        const result = await response.json();
        alert(`Success: ${result.message}`);
        setSelectedFile(null);
        fileInputRef.current.value = '';
      } else {
        const error = await response.text();
        alert(`Error: ${error}`);
      }
    } catch (error) {
      console.error('Upload error:', error);
      alert('Upload failed. Please try again.');
    } finally {
      setIsUploading(false);
    }
  };

  const reindexDocuments = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/ingest/reindex`, {
        method: 'POST'
      });
      
      if (response.ok) {
        const result = await response.json();
        alert(`Success: ${result.message}`);
      } else {
        const error = await response.text();
        alert(`Error: ${error}`);
      }
    } catch (error) {
      console.error('Reindex error:', error);
      alert('Reindex failed. Please try again.');
    }
  };

  const selectSession = (sessionId) => {
    setCurrentSessionId(sessionId);
    loadChatMessages(sessionId);
    connectWebSocket(sessionId);
  };

  const formatMessage = (content) => {
    // Convert markdown-style image references to actual images
    const imageRegex = /!\[Image\]\(([^)]+)\)/g;
    const parts = content.split(imageRegex);
    
    const result = [];
    for (let i = 0; i < parts.length; i++) {
      if (i % 2 === 0) {
        // Text part
        result.push(
          <span key={i} className="whitespace-pre-wrap">
            {parts[i]}
          </span>
        );
      } else {
        // Image reference part
        result.push(
          <span key={i} className="inline-block bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 px-2 py-1 rounded text-sm mx-1">
            📷 {parts[i]}
          </span>
        );
      }
    }
    
    return result;
  };

  // Start first session if none exists
  useEffect(() => {
    if (chatSessions.length === 0) {
      createNewSession();
    } else if (currentSessionId && !websocketRef.current) {
      connectWebSocket(currentSessionId);
    }
  }, [chatSessions, currentSessionId]);

  return (
    <div className={`min-h-screen transition-colors duration-200 ${darkMode ? 'dark bg-gray-900' : 'bg-gray-50'}`}>
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              🔧 Qualtrics Troubleshooter
            </h1>
            <div className={`px-3 py-1 rounded-full text-sm font-medium ${isConnected ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'}`}>
              {isConnected ? '🟢 Connected' : '🔴 Disconnected'}
            </div>
          </div>
          
          <div className="flex items-center space-x-4">
            {/* File Upload */}
            <div className="flex items-center space-x-2">
              <input
                type="file"
                ref={fileInputRef}
                accept=".docx"
                onChange={(e) => setSelectedFile(e.target.files[0])}
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                📄 Upload Manual
              </button>
              {selectedFile && (
                <button
                  onClick={handleFileUpload}
                  disabled={isUploading}
                  className="bg-green-600 hover:bg-green-700 disabled:bg-gray-400 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                >
                  {isUploading ? '⏳ Uploading...' : '✅ Process'}
                </button>
              )}
            </div>
            
            <button
              onClick={reindexDocuments}
              className="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              🔄 Reindex
            </button>
            
            <button
              onClick={() => setDarkMode(!darkMode)}
              className="bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-gray-800 dark:text-gray-200 p-2 rounded-lg transition-colors"
            >
              {darkMode ? '☀️' : '🌙'}
            </button>
          </div>
        </div>
      </div>

      <div className="flex h-[calc(100vh-80px)]">
        {/* Sidebar */}
        <div className="w-80 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex flex-col">
          <div className="p-4 border-b border-gray-200 dark:border-gray-700">
            <button
              onClick={createNewSession}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-medium transition-colors"
            >
              ➕ New Chat
            </button>
          </div>
          
          <div className="flex-1 overflow-y-auto">
            {chatSessions.map((session) => (
              <div
                key={session.id}
                onClick={() => selectSession(session.id)}
                className={`p-4 border-b border-gray-200 dark:border-gray-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors ${currentSessionId === session.id ? 'bg-blue-50 dark:bg-blue-900 border-r-2 border-blue-500' : ''}`}
              >
                <div className="font-medium text-gray-900 dark:text-white truncate">
                  {session.title}
                </div>
                <div className="text-sm text-gray-500 dark:text-gray-400">
                  {new Date(session.created_at).toLocaleDateString()}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Main Chat Area */}
        <div className="flex-1 flex flex-col">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {messages.length === 0 && (
              <div className="text-center py-12">
                <div className="text-6xl mb-4">🔧</div>
                <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
                  Welcome to Qualtrics Troubleshooter
                </h2>
                <p className="text-gray-600 dark:text-gray-400 max-w-md mx-auto">
                  Ask me anything about Qualtrics surveys! I can help you troubleshoot issues, explain features, and guide you through solutions.
                </p>
              </div>
            )}
            
            {messages.map((message) => (
              <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-4xl ${message.role === 'user' ? 'order-2' : 'order-1'}`}>
                  <div className={`flex items-start space-x-3 ${message.role === 'user' ? 'flex-row-reverse space-x-reverse' : ''}`}>
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-white font-medium ${message.role === 'user' ? 'bg-blue-600' : 'bg-purple-600'}`}>
                      {message.role === 'user' ? '👤' : '🔧'}
                    </div>
                    
                    <div className={`rounded-2xl px-4 py-3 ${message.role === 'user' ? 'bg-blue-600 text-white' : 'bg-white dark:bg-gray-800 text-gray-900 dark:text-white border border-gray-200 dark:border-gray-700'}`}>
                      <div className="text-base leading-relaxed">
                        {formatMessage(message.content)}
                      </div>
                      
                      {/* Display images */}
                      {message.images && message.images.length > 0 && (
                        <div className="mt-3 space-y-2">
                          {message.images.map((image, index) => (
                            <div key={index} className="relative">
                              <img
                                src={`data:image/png;base64,${image.data}`}
                                alt={`Reference ${image.id}`}
                                className="max-w-xs rounded-lg border border-gray-200 dark:border-gray-600 cursor-pointer hover:opacity-80 transition-opacity"
                                onClick={() => setExpandedImage(image)}
                              />
                              <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                                📷 {image.id}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {message.isStreaming && (
                        <div className="flex items-center mt-2 space-x-1">
                          <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                          <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{animationDelay: '0.1s'}}></div>
                          <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{animationDelay: '0.2s'}}></div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
            
            {isTyping && (
              <div className="flex justify-start">
                <div className="max-w-4xl">
                  <div className="flex items-start space-x-3">
                    <div className="w-8 h-8 rounded-full bg-purple-600 flex items-center justify-center text-white font-medium">
                      🔧
                    </div>
                    <div className="bg-white dark:bg-gray-800 rounded-2xl px-4 py-3 border border-gray-200 dark:border-gray-700">
                      <div className="flex items-center space-x-1">
                        <div className="w-2 h-2 bg-purple-500 rounded-full animate-bounce"></div>
                        <div className="w-2 h-2 bg-purple-500 rounded-full animate-bounce" style={{animationDelay: '0.1s'}}></div>
                        <div className="w-2 h-2 bg-purple-500 rounded-full animate-bounce" style={{animationDelay: '0.2s'}}></div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
            
            <div ref={messagesEndRef} />
          </div>

          {/* Input Area */}
          <div className="border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-6">
            <div className="max-w-4xl mx-auto">
              <div className="flex items-end space-x-4">
                <div className="flex-1">
                  <textarea
                    value={inputMessage}
                    onChange={(e) => setInputMessage(e.target.value)}
                    onKeyPress={handleKeyPress}
                    placeholder="Ask about Qualtrics issues, errors, or features..."
                    className="w-full resize-none rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-4 py-3 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 text-lg"
                    rows="3"
                    disabled={!isConnected || isTyping}
                  />
                </div>
                <button
                  onClick={sendMessage}
                  disabled={!inputMessage.trim() || !isConnected || isTyping}
                  className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white p-3 rounded-xl transition-colors"
                >
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                  </svg>
                </button>
              </div>
              <div className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                Press Enter to send, Shift+Enter for new line
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Image Modal */}
      {expandedImage && (
        <div className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4">
          <div className="relative max-w-4xl max-h-full">
            <button
              onClick={() => setExpandedImage(null)}
              className="absolute top-4 right-4 bg-black bg-opacity-50 text-white rounded-full p-2 hover:bg-opacity-75 transition-opacity"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
            <img
              src={`data:image/png;base64,${expandedImage.data}`}
              alt={`Reference ${expandedImage.id}`}
              className="max-w-full max-h-full rounded-lg"
            />
            <div className="absolute bottom-4 left-4 bg-black bg-opacity-50 text-white px-3 py-1 rounded">
              📷 {expandedImage.id}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;