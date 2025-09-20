import os
import jwt
import bcrypt
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, current_app
import mysql.connector
from mysql.connector import Error
import logging

logger = logging.getLogger(__name__)

class AuthManager:
    def __init__(self, db_config, jwt_secret_key, jwt_algorithm='HS256'):
        self.db_config = db_config
        self.jwt_secret_key = jwt_secret_key
        self.jwt_algorithm = jwt_algorithm
        self.access_token_expires = timedelta(hours=1)
        self.refresh_token_expires = timedelta(days=30)
        self.init_database()
    
    def get_db_connection(self):
        """Create and return a database connection"""
        try:
            connection = mysql.connector.connect(**self.db_config)
            return connection
        except Error as e:
            logger.error(f"Error connecting to MySQL: {e}")
            raise
    
    def init_database(self):
        """Initialize the database with required tables"""
        connection = None  # Initialize connection variable
        cursor = None      # Initialize cursor variable
        try:
            connection = self.get_db_connection()
            cursor = connection.cursor()
            
            # Create users table
            create_users_table = """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                first_name VARCHAR(100) NOT NULL,
                last_name VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
            """
            
            # Create refresh tokens table
            create_refresh_tokens_table = """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                token_hash VARCHAR(255) NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_revoked BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
            
            cursor.execute(create_users_table)
            cursor.execute(create_refresh_tokens_table)
            connection.commit()
            logger.info("Database tables initialized successfully")
            
        except Error as e:
            logger.error(f"Error initializing database: {e}")
            raise
        finally:
            # Proper cleanup with null checks
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()
    
    def hash_password(self, password):
        """Hash a password using bcrypt"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def verify_password(self, password, password_hash):
        """Verify a password against its hash"""
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    
    def generate_tokens(self, user_id, email):
        """Generate access and refresh tokens"""
        now = datetime.utcnow()
        
        # Access token payload
        access_payload = {
            'user_id': user_id,
            'email': email,
            'exp': now + self.access_token_expires,
            'iat': now,
            'type': 'access'
        }
        
        # Refresh token payload
        refresh_payload = {
            'user_id': user_id,
            'exp': now + self.refresh_token_expires,
            'iat': now,
            'type': 'refresh'
        }
        
        access_token = jwt.encode(access_payload, self.jwt_secret_key, algorithm=self.jwt_algorithm)
        refresh_token = jwt.encode(refresh_payload, self.jwt_secret_key, algorithm=self.jwt_algorithm)
        
        # Store refresh token in database
        self.store_refresh_token(user_id, refresh_token)
        
        return access_token, refresh_token
    
    def store_refresh_token(self, user_id, refresh_token):
        """Store refresh token in database"""
        connection = None
        cursor = None
        try:
            connection = self.get_db_connection()
            cursor = connection.cursor()
            
            # Hash the refresh token before storing
            token_hash = bcrypt.hashpw(refresh_token.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            expires_at = datetime.utcnow() + self.refresh_token_expires
            
            query = """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
            VALUES (%s, %s, %s)
            """
            cursor.execute(query, (user_id, token_hash, expires_at))
            connection.commit()
            
        except Error as e:
            logger.error(f"Error storing refresh token: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()
    
    def create_user(self, email, password, first_name, last_name):
        """Create a new user"""
        connection = None
        cursor = None
        try:
            connection = self.get_db_connection()
            cursor = connection.cursor()
            
            # Check if user already exists
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                return {'success': False, 'message': 'Email already registered'}
            
            # Hash password and create user
            password_hash = self.hash_password(password)
            query = """
            INSERT INTO users (email, password_hash, first_name, last_name)
            VALUES (%s, %s, %s, %s)
            """
            cursor.execute(query, (email, password_hash, first_name, last_name))
            connection.commit()
            
            user_id = cursor.lastrowid
            logger.info(f"User created successfully with ID: {user_id}")
            
            return {'success': True, 'user_id': user_id, 'message': 'User created successfully'}
            
        except Error as e:
            logger.error(f"Error creating user: {e}")
            return {'success': False, 'message': 'Failed to create user'}
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()
    
    def authenticate_user(self, email, password):
        """Authenticate a user with email and password"""
        connection = None
        cursor = None
        try:
            connection = self.get_db_connection()
            cursor = connection.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT id, email, password_hash, first_name, last_name, is_active
                FROM users WHERE email = %s
            """, (email,))
            
            user = cursor.fetchone()
            if not user:
                return {'success': False, 'message': 'Invalid credentials'}
            
            if not user['is_active']:
                return {'success': False, 'message': 'Account is deactivated'}
            
            if not self.verify_password(password, user['password_hash']):
                return {'success': False, 'message': 'Invalid credentials'}
            
            # Generate tokens
            access_token, refresh_token = self.generate_tokens(user['id'], user['email'])
            
            return {
                'success': True,
                'user': {
                    'id': user['id'],
                    'email': user['email'],
                    'first_name': user['first_name'],
                    'last_name': user['last_name']
                },
                'access_token': access_token,
                'refresh_token': refresh_token
            }
            
        except Error as e:
            logger.error(f"Error authenticating user: {e}")
            return {'success': False, 'message': 'Authentication failed'}
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()
    
    def verify_token(self, token, token_type='access'):
        """Verify a JWT token"""
        try:
            payload = jwt.decode(token, self.jwt_secret_key, algorithms=[self.jwt_algorithm])
            
            if payload.get('type') != token_type:
                return {'valid': False, 'message': 'Invalid token type'}
            
            return {'valid': True, 'payload': payload}
            
        except jwt.ExpiredSignatureError:
            return {'valid': False, 'message': 'Token has expired'}
        except jwt.InvalidTokenError:
            return {'valid': False, 'message': 'Invalid token'}
    
    def refresh_access_token(self, refresh_token):
        """Generate new access token using refresh token"""
        connection = None
        cursor = None
        try:
            # Verify refresh token
            result = self.verify_token(refresh_token, 'refresh')
            if not result['valid']:
                return {'success': False, 'message': result['message']}
            
            payload = result['payload']
            user_id = payload['user_id']
            
            # Check if refresh token exists and is not revoked
            connection = self.get_db_connection()
            cursor = connection.cursor()
            
            cursor.execute("""
                SELECT id FROM refresh_tokens 
                WHERE user_id = %s AND expires_at > NOW() AND is_revoked = FALSE
            """, (user_id,))
            
            if not cursor.fetchone():
                return {'success': False, 'message': 'Refresh token invalid or revoked'}
            
            # Get user info
            cursor.execute("""
                SELECT email FROM users WHERE id = %s AND is_active = TRUE
            """, (user_id,))
            
            user = cursor.fetchone()
            if not user:
                return {'success': False, 'message': 'User not found or inactive'}
            
            # Generate new access token
            now = datetime.utcnow()
            access_payload = {
                'user_id': user_id,
                'email': user[0],
                'exp': now + self.access_token_expires,
                'iat': now,
                'type': 'access'
            }
            
            new_access_token = jwt.encode(access_payload, self.jwt_secret_key, algorithm=self.jwt_algorithm)
            
            return {'success': True, 'access_token': new_access_token}
            
        except Error as e:
            logger.error(f"Error refreshing token: {e}")
            return {'success': False, 'message': 'Failed to refresh token'}
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()
    
    def revoke_refresh_token(self, user_id, refresh_token=None):
        """Revoke refresh token(s)"""
        connection = None
        cursor = None
        try:
            connection = self.get_db_connection()
            cursor = connection.cursor()
            
            if refresh_token:
                # Revoke specific token
                cursor.execute("""
                    UPDATE refresh_tokens SET is_revoked = TRUE 
                    WHERE user_id = %s AND token_hash = %s
                """, (user_id, bcrypt.hashpw(refresh_token.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')))
            else:
                # Revoke all tokens for user
                cursor.execute("""
                    UPDATE refresh_tokens SET is_revoked = TRUE WHERE user_id = %s
                """, (user_id,))
            
            connection.commit()
            return {'success': True}
            
        except Error as e:
            logger.error(f"Error revoking refresh token: {e}")
            return {'success': False, 'message': 'Failed to revoke token'}
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()

def token_required(f):
    """Decorator to require valid JWT token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        
        if auth_header:
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            auth_manager = current_app.auth_manager
            result = auth_manager.verify_token(token, 'access')
            
            if not result['valid']:
                return jsonify({'error': result['message']}), 401
            
            request.current_user = result['payload']
            
        except Exception as e:
            return jsonify({'error': 'Token verification failed'}), 401
        
        return f(*args, **kwargs)
    
    return decorated