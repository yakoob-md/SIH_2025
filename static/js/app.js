// Global variables
console.log("app.js loaded")
let currentSessionId = null;
let sessions = [];
let uploadModal = null;

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    // Initialize Bootstrap modal
    uploadModal = new bootstrap.Modal(document.getElementById('uploadModal'));
    
    // Load all sessions on startup
    loadSessions();
    
    // Set up auto-resize for chat input
    setupChatInput();
});

// Session Management Functions
async function loadSessions() {
    try {
        const response = await fetch('/api/sessions');
        const data = await response.json();
        
        if (data.success) {
            sessions = data.sessions;
            renderSessions();
            
            // If no sessions, show welcome state
            if (sessions.length === 0) {
                showWelcomeState();
            }
        } else {
            console.error('Error loading sessions:', data.error);
            showError('Failed to load documents');
        }
    } catch (error) {
        console.error('Error loading sessions:', error);
        showError('Failed to connect to server');
    }
}

function renderSessions() {
    const sessionsList = document.getElementById('sessionsList');
    
    if (sessions.length === 0) {
        sessionsList.innerHTML = `
            <div class="text-center text-muted p-3">
                <i class="bi bi-folder2-open"></i><br>
                <small>No documents uploaded yet</small>
            </div>
        `;
        return;
    }
    
    sessionsList.innerHTML = sessions.map(session => `
        <div class="session-item ${session.session_id === currentSessionId ? 'active' : ''}" 
             onclick="selectSession('${session.session_id}')">
            <div class="session-name">
                <i class="${getFileIcon(session.file_type)}"></i>
                <span title="${session.document_name}">${truncateText(session.document_name, 25)}</span>
            </div>
            <div class="session-meta">
                <span class="session-date">${formatDate(session.created_at)}</span>
                <div class="session-actions">
                    <button class="delete-session-btn" onclick="deleteSession('${session.session_id}', event)" title="Delete">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

async function selectSession(sessionId) {
    try {
        // Update UI immediately
        currentSessionId = sessionId;
        renderSessions(); // Re-render to show active state
        
        // Show loading state
        showChatLoading();
        
        // Fetch session details and chat history
        const response = await fetch(`/api/sessions/${sessionId}`);
        const data = await response.json();
        
        if (data.success) {
            // Update chat header
            updateChatHeader(data.session);
            
            // Load chat history
            loadChatHistory(data.chat_history);
            
            // Show chat interface
            showChatInterface();
        } else {
            console.error('Error loading session:', data.error);
            showError('Failed to load document');
        }
    } catch (error) {
        console.error('Error selecting session:', error);
        showError('Failed to load document');
    }
}

async function deleteSession(sessionId, event) {
    event.stopPropagation(); // Prevent session selection
    
    if (!confirm('Are you sure you want to delete this document and all its chat history?')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/sessions/${sessionId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Remove from sessions array
            sessions = sessions.filter(s => s.session_id !== sessionId);
            
            // If this was the current session, reset view
            if (currentSessionId === sessionId) {
                currentSessionId = null;
                if (sessions.length > 0) {
                    // Select the first available session
                    selectSession(sessions[0].session_id);
                } else {
                    showWelcomeState();
                }
            }
            
            // Re-render sessions
            renderSessions();
            
            showSuccess('Document deleted successfully');
        } else {
            console.error('Error deleting session:', data.error);
            showError('Failed to delete document');
        }
    } catch (error) {
        console.error('Error deleting session:', error);
        showError('Failed to delete document');
    }
}

// Chat Functions
function loadChatHistory(messages) {
    const messagesContainer = document.getElementById('messagesContainer');
    
    if (messages.length === 0) {
        messagesContainer.innerHTML = `
            <div class="text-center text-muted p-4">
                <i class="bi bi-chat-text" style="font-size: 2rem;"></i>
                <p class="mt-2 mb-0">Start a conversation with your document!</p>
                <small>Ask questions about the content, request summaries, or seek clarifications.</small>
            </div>
        `;
        return;
    }
    
    messagesContainer.innerHTML = messages.map(message => `
        <div class="message ${message.role}">
            <div class="message-avatar">
                ${message.role === 'user' ? 'U' : 'AI'}
            </div>
            <div class="message-content">
                ${formatMessageContent(message.content)}
            </div>
        </div>
    `).join('');
    
    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

async function sendMessage() {
    const chatInput = document.getElementById('chatInput');
    const message = chatInput.value.trim();
    
    if (!message || !currentSessionId) return;
    
    // Disable input and show loading
    const sendBtn = document.getElementById('sendBtn');
    chatInput.disabled = true;
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<div class="spinner"></div>';
    
    // Add user message to UI immediately
    addMessageToUI('user', message);
    chatInput.value = '';
    
    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: currentSessionId,
                message: message
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Add AI response to UI
            addMessageToUI('assistant', data.response);
        } else {
            console.error('Error sending message:', data.error);
            showError('Failed to send message');
        }
    } catch (error) {
        console.error('Error sending message:', error);
        showError('Failed to send message');
    } finally {
        // Re-enable input
        chatInput.disabled = false;
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<i class="bi bi-send"></i>';
        chatInput.focus();
    }
}

function addMessageToUI(role, content) {
    const messagesContainer = document.getElementById('messagesContainer');
    
    // Remove empty state if present
    const emptyState = messagesContainer.querySelector('.text-center.text-muted');
    if (emptyState) {
        emptyState.remove();
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    messageDiv.innerHTML = `
        <div class="message-avatar">
            ${role === 'user' ? 'U' : 'AI'}
        </div>
        <div class="message-content">
            ${formatMessageContent(content)}
        </div>
    `;
    
    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Upload Functions
function openUploadModal() {
    document.getElementById('fileInput').value = '';
    document.getElementById('uploadProgress').style.display = 'none';
    uploadModal.show();
}

async function uploadDocument() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];
    
    if (!file) {
        showError('Please select a file');
        return;
    }
    
    // Show progress
    const uploadProgress = document.getElementById('uploadProgress');
    uploadProgress.style.display = 'block';
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Close modal
            uploadModal.hide();
            
            // Reload sessions
            await loadSessions();
            
            // Select the new session
            selectSession(data.session_id);
            
            showSuccess(data.message);
        } else {
            console.error('Upload error:', data.error);
            showError(data.error || 'Failed to upload document');
        }
    } catch (error) {
        console.error('Upload error:', error);
        showError('Failed to upload document');
    } finally {
        uploadProgress.style.display = 'none';
    }
}

// UI Helper Functions
function showWelcomeState() {
    document.getElementById('welcomeState').style.display = 'flex';
    document.getElementById('chatContainer').style.display = 'none';
    document.getElementById('chatHeader').style.display = 'none';
    currentSessionId = null;
}

function showChatInterface() {
    document.getElementById('welcomeState').style.display = 'none';
    document.getElementById('chatContainer').style.display = 'flex';
    document.getElementById('chatHeader').style.display = 'flex';
}

function showChatLoading() {
    const messagesContainer = document.getElementById('messagesContainer');
    messagesContainer.innerHTML = `
        <div class="text-center p-4">
            <div class="loading">
                <div class="spinner"></div>
                Loading chat history...
            </div>
        </div>
    `;
    showChatInterface();
}

function updateChatHeader(session) {
    document.getElementById('chatTitle').textContent = session.document_name;
    document.getElementById('chatSubtitle').textContent = 
        `Uploaded ${formatDate(session.created_at)} • ${session.file_type.toUpperCase()}`;
}

function setupChatInput() {
    const chatInput = document.getElementById('chatInput');
    
    chatInput.addEventListener('input', function() {
        // Auto-resize textarea
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 150) + 'px';
    });
}

function handleInputKeypress(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

// Utility Functions
function getFileIcon(fileType) {
    const iconMap = {
        'pdf': 'bi-file-earmark-pdf text-danger',
        'docx': 'bi-file-earmark-word text-primary',
        'doc': 'bi-file-earmark-word text-primary',
        'txt': 'bi-file-earmark-text text-secondary'
    };
    return iconMap[fileType?.toLowerCase()] || 'bi-file-earmark text-secondary';
}

function truncateText(text, maxLength) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength - 3) + '...';
}

function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diffTime = Math.abs(now - date);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    
    if (diffDays === 1) return 'Today';
    if (diffDays === 2) return 'Yesterday';
    if (diffDays <= 7) return `${diffDays - 1} days ago`;
    
    return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric',
        year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
    });
}

function formatMessageContent(content) {
    // Simple formatting - you can enhance this with markdown support
    return content
        .replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>');
}

// Notification Functions
function showSuccess(message) {
    showNotification(message, 'success');
}

function showError(message) {
    showNotification(message, 'danger');
}

function showNotification(message, type) {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
    notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    document.body.appendChild(notification);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, 5000);
}