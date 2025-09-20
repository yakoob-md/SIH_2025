import os
import uuid
import logging
import tempfile
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from dotenv import load_dotenv
from openai import OpenAI
from urllib.parse import urlparse
import io

from session_manager import SessionManager
from document_parser import DocumentParser
from vector_store import VectorStore
from chat_engine import ChatEngine
from auth import AuthManager, token_required

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_FILE_SIZE_MB', 5)) * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'uploads')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', os.urandom(24))
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Parse MySQL database URL
def parse_database_url(database_url):
    """Parse MySQL database URL and return connection config"""
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    
    parsed = urlparse(database_url)
    
    return {
        'host': parsed.hostname,
        'port': parsed.port or 3306,
        'user': parsed.username,
        'password': parsed.password,
        'database': parsed.path[1:] if parsed.path else None,  # Remove leading '/'
        'charset': 'utf8mb4',
        'collation': 'utf8mb4_unicode_ci',
        'autocommit': True
    }

# Initialize components
session_manager = SessionManager()

try:
    # Initialize OpenAI client
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    # Initialize document processing components
    document_parser = DocumentParser(
        chunk_size=int(os.getenv('CHUNK_SIZE_TOKENS', 800)),
        chunk_overlap=int(os.getenv('CHUNK_OVERLAP_TOKENS', 100)),
        ocr_threshold=int(os.getenv('OCR_MIN_TEXT_THRESHOLD', 50))
    )
    
    vector_store = VectorStore(
        openai_client=openai_client,
        embedding_model=os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small'),
        embeddings_folder=os.getenv('EMBEDDINGS_FOLDER', 'embeddings')
    )
    
    chat_engine = ChatEngine(
        openai_client=openai_client,
        chat_model=os.getenv('CHAT_MODEL', 'gpt-4o-mini')
    )
    
    # Initialize authentication manager
    db_config = parse_database_url(os.getenv('DATABASE_URL'))
    jwt_secret = os.getenv('JWT_SECRET_KEY', os.urandom(32).hex())
    
    auth_manager = AuthManager(
        db_config=db_config,
        jwt_secret_key=jwt_secret
    )
    
    # Make auth_manager available to the app
    app.auth_manager = auth_manager
    
    logger.info("All components initialized successfully")
    
except Exception as e:
    logger.error(f"Failed to initialize components: {str(e)}")
    raise

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'txt'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_type(filename):
    return filename.rsplit('.', 1)[1].lower()

# Error handlers
@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    return jsonify({'error': f'File too large. Max size is {app.config["MAX_CONTENT_LENGTH"] // (1024*1024)}MB'}), 413

@app.errorhandler(500)
def handle_internal_error(e):
    logger.error(f"Internal server error: {str(e)}")
    return jsonify({'error': 'Internal server error occurred', 'message': 'Please try again later'}), 500

# Authentication routes
@app.route('/login', methods=['GET'])
def login_page():
    return render_template('login.html')

@app.route('/signup', methods=['GET'])
def signup_page():
    return render_template('signup.html')

@app.route('/auth/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['email', 'password', 'firstName', 'lastName']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'message': f'{field} is required'}), 400
        
        # Basic email validation
        email = data['email'].lower().strip()
        if '@' not in email or '.' not in email:
            return jsonify({'success': False, 'message': 'Invalid email format'}), 400
        
        # Password strength validation (basic)
        password = data['password']
        if len(password) < 8:
            return jsonify({'success': False, 'message': 'Password must be at least 8 characters long'}), 400
        
        # Create user
        result = auth_manager.create_user(
            email=email,
            password=password,
            first_name=data['firstName'].strip(),
            last_name=data['lastName'].strip()
        )
        
        if result['success']:
            return jsonify({'success': True, 'message': 'Account created successfully'})
        else:
            return jsonify({'success': False, 'message': result['message']}), 400
            
    except Exception as e:
        logger.error(f"Signup error: {str(e)}")
        return jsonify({'success': False, 'message': 'Failed to create account'}), 500

@app.route('/auth/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('email') or not data.get('password'):
            return jsonify({'success': False, 'message': 'Email and password are required'}), 400
        
        # Authenticate user
        result = auth_manager.authenticate_user(
            email=data['email'].lower().strip(),
            password=data['password']
        )
        
        if result['success']:
            return jsonify({
                'success': True,
                'user': result['user'],
                'access_token': result['access_token'],
                'refresh_token': result['refresh_token']
            })
        else:
            return jsonify({'success': False, 'message': result['message']}), 401
            
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'success': False, 'message': 'Login failed'}), 500

@app.route('/auth/refresh', methods=['POST'])
def refresh_token():
    try:
        data = request.get_json()
        refresh_token = data.get('refresh_token')
        
        if not refresh_token:
            return jsonify({'success': False, 'message': 'Refresh token is required'}), 400
        
        result = auth_manager.refresh_access_token(refresh_token)
        
        if result['success']:
            return jsonify({
                'success': True,
                'access_token': result['access_token']
            })
        else:
            return jsonify({'success': False, 'message': result['message']}), 401
            
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        return jsonify({'success': False, 'message': 'Token refresh failed'}), 500

@app.route('/auth/logout', methods=['POST'])
@token_required
def logout():
    try:
        data = request.get_json()
        refresh_token = data.get('refresh_token')
        user_id = request.current_user['user_id']
        
        # Revoke refresh token(s)
        auth_manager.revoke_refresh_token(user_id, refresh_token)
        
        return jsonify({'success': True, 'message': 'Logged out successfully'})
        
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        return jsonify({'success': False, 'message': 'Logout failed'}), 500

@app.route('/auth/verify-token', methods=['GET'])
@token_required
def verify_token():
    try:
        return jsonify({
            'valid': True,
            'user': {
                'id': request.current_user['user_id'],
                'email': request.current_user['email']
            }
        })
    except Exception as e:
        logger.error(f"Token verification error: {str(e)}")
        return jsonify({'valid': False, 'message': 'Token verification failed'}), 401

# Main application routes (now protected)
@app.route('/', methods=['GET'])
def home():
    return render_template('index2.html')

@app.route('/upload', methods=['POST'])
@token_required
def upload_document():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        filename = file.filename
        file_type = get_file_type(filename)

        if not allowed_file(filename):
            return jsonify({'error': f'Unsupported file type: {file_type}'}), 400

        temp_file_path = os.path.join('temp', filename)
        os.makedirs('temp', exist_ok=True)
        file.save(temp_file_path)

        # Associate session with user
        user_id = request.current_user['user_id']
        session_id = session_manager.create_session(filename, temp_file_path, file_type, user_id)

        # Use the session file path for parsing and embedding
        full_path = session_manager.get_session_file_path(session_id)
        file_info = document_parser.get_file_info(full_path)
        extracted_text = document_parser.parse_document(full_path, file_type)
        chunks = document_parser.chunk_text(extracted_text)

        success = vector_store.create_embeddings(chunks, session_id)

        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        return jsonify({
            'success': True,
            'session_id': session_id,
            'file_info': file_info,
            'message': f'Document "{filename}" uploaded successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions', methods=['GET'])
@token_required
def get_all_sessions():
    try:
        user_id = request.current_user['user_id']
        sessions = session_manager.get_user_sessions(user_id)
        logger.info(f"[API] Sessions returned for user {user_id}: {sessions}")

        serialized_sessions = []
        for s in sessions:
            logger.info(f"[API] Processing session: {s}")
            serialized_sessions.append({
                'id': s.get('session_id', 'undefined'),
                'filename': s.get('document_name', 'undefined'),
                'created_at': s.get('created_at', 'undefined')
            })

        return jsonify({'success': True, 'sessions': serialized_sessions})
    except Exception as e:
        logger.error(f"[API] Failed to fetch sessions: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<session_id>', methods=['GET'])
@token_required
def get_session_details(session_id):
    try:
        user_id = request.current_user['user_id']
        session = session_manager.get_user_session(session_id, user_id)
        
        if not session:
            return jsonify({'error': 'Session not found or access denied'}), 404

        session_manager.update_last_accessed(session_id)
        chat_history = session_manager.get_chat_history(session_id)

        # Apply fallback logic here
        session['document_name'] = session.get('document_name') or session.get('filename') or "Untitled Document"
        session['file_type'] = session.get('file_type', 'pdf')
        session['created_at'] = session.get('created_at', 'Unknown')

        return jsonify({'success': True, 'session': session, 'chat_history': chat_history})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/chat', methods=['POST'])
@token_required
def chat():
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        user_message = data.get('message')
        user_id = request.current_user['user_id']

        if not session_id or not user_message:
            return jsonify({'error': 'Session ID and message are required'}), 400

        # Verify user owns this session
        if not session_manager.user_owns_session(session_id, user_id):
            return jsonify({'error': 'Session not found or access denied'}), 404

        # Get relevant chunks
        relevant_chunks = vector_store.similarity_search(user_message, session_id)

        # Get conversation history
        conversation_history = session_manager.get_chat_history(session_id)

        # Generate response
        result = chat_engine.generate_response(user_message, relevant_chunks, conversation_history)

        # Store messages
        session_manager.add_chat_message(session_id, 'user', user_message)
        session_manager.add_chat_message(session_id, 'assistant', result['response'])
        session_manager.update_last_accessed(session_id)

        return jsonify({
            'success': True,
            'response': result['response'],
            'session_id': session_id,
            'sources_used': result.get('sources_used'),
            'confidence': result.get('confidence'),
            'chunks': result.get('relevant_chunks'),
            'usage': result.get('usage')
        })
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<session_id>', methods=['DELETE'])
@token_required
def delete_session(session_id):
    try:
        user_id = request.current_user['user_id']
        
        # Verify user owns this session
        if not session_manager.user_owns_session(session_id, user_id):
            return jsonify({'error': 'Session not found or access denied'}), 404
            
        if session_manager.delete_session(session_id):
            return jsonify({'success': True, 'message': 'Session deleted successfully'})
        else:
            return jsonify({'error': 'Failed to delete session'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/chat/<session_id>')
def chat_page(session_id):
   

    return render_template('chat.html', chat_session={'session_id':session_id})

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'service': 'document-qa-api', 'version': '1.0.0'})



# Voice: Speech-to-Text (STT)
@app.route('/api/voice/stt', methods=['POST'])
@token_required
def voice_transcribe():
    try:
        if 'audio' not in request.files:
            return jsonify({'success': False, 'message': 'No audio file provided'}), 400

        audio_file = request.files['audio']
        raw_lang = (request.form.get('language') or '').strip().lower()
        # Sanitize to ISO-639-1 (two-letter) if provided
        language = ''
        if raw_lang:
            language = raw_lang.split('-')[0][:2]

        # Save to a temp file to interop with OpenAI SDK easily
        os.makedirs('temp', exist_ok=True)
        file_name = getattr(audio_file, 'filename', 'audio.webm') or 'audio.webm'
        temp_path = os.path.join('temp', file_name)
        audio_file.save(temp_path)

        # OpenAI transcription (multilingual)
        # whisper-1 supports many languages; set language hint if provided
        with open(temp_path, 'rb') as f:
            kwargs = {
                'model': os.getenv('WHISPER_MODEL', 'whisper-1'),
                'file': f,
            }
            if language:
                kwargs['language'] = language
            transcription = openai_client.audio.transcriptions.create(**kwargs)

        text = getattr(transcription, 'text', None)
        if not text:
            return jsonify({'success': False, 'message': 'Transcription failed'}), 500

        return jsonify({'success': True, 'text': text})
    except Exception as e:
        logger.error(f"STT error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Transcription error', 'error': str(e)}), 500
    finally:
        try:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


# Voice: Text-to-Speech (TTS)
@app.route('/api/voice/tts', methods=['POST'])
@token_required
def voice_tts():
    try:
        data = request.get_json()
        text = (data or {}).get('text')
        voice = (data or {}).get('voice', 'alloy')
        audio_format = (data or {}).get('format', 'mp3')

        if not text or not text.strip():
            return jsonify({'success': False, 'message': 'Text is required'}), 400

        # OpenAI TTS - generate audio directly
        tts_model = os.getenv('TTS_MODEL', 'tts-1')
        
        try:
            result = openai_client.audio.speech.create(
                model=tts_model,
                voice=voice,
                input=text,
                format=audio_format
            )
        except Exception as e:
            logger.warning(f"TTS failed for original text, trying English fallback: {str(e)}")
            # Fallback: try with English text if regional language fails
            try:
                # Simple fallback - just try with a basic English message
                fallback_text = f"Here is the response: {text[:100]}..." if len(text) > 100 else text
                result = openai_client.audio.speech.create(
                    model=tts_model,
                    voice=voice,
                    input=fallback_text,
                    format=audio_format
                )
            except Exception as fallback_error:
                logger.error(f"TTS fallback also failed: {str(fallback_error)}")
                raise fallback_error

        # Extract raw audio bytes
        audio_bytes = result.content
        if not audio_bytes:
            return jsonify({'success': False, 'message': 'TTS generation failed'}), 500

        mime = 'audio/mpeg' if audio_format == 'mp3' else f'audio/{audio_format}'
        mem_file = io.BytesIO(audio_bytes)
        mem_file.seek(0)
        return send_file(mem_file, mimetype=mime, as_attachment=False, download_name=f'speech.{audio_format}')
    except Exception as e:
        logger.error(f"TTS error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'TTS error', 'error': str(e)}), 500
    finally:
        pass


if __name__ == '__main__':
    required_env_vars = ['OPENAI_API_KEY', 'DATABASE_URL', 'JWT_SECRET_KEY']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]

    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        print("Please check your .env file and ensure all required variables are set.")
        print("Required variables:")
        print("- OPENAI_API_KEY: Your OpenAI API key")
        print("- DATABASE_URL: MySQL database URL (mysql://user:password@host:port/database)")
        print("- JWT_SECRET_KEY: Secret key for JWT token signing")
        exit(1)

    logger.info("Starting Flask application...")
    app.run(debug=False, host='0.0.0.0', port=5000)