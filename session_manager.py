import os
import json
import uuid
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self, sessions_file='sessions.json'):
        self.sessions_file = sessions_file
        self.sessions = self.load_sessions()

    def load_sessions(self):
        """Load sessions from file"""
        try:
            if os.path.exists(self.sessions_file):
                with open(self.sessions_file, 'r') as f:
                    sessions = json.load(f)
                    for session_id, session_data in sessions.items():
                        if 'user_id' not in session_data:
                            session_data['user_id'] = None
                    return sessions
            return {}
        except Exception as e:
            logger.error(f"Error loading sessions: {e}")
            return {}

    def save_sessions(self):
        """Save sessions to file"""
        try:
            with open(self.sessions_file, 'w') as f:
                json.dump(self.sessions, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving sessions: {e}")

    def create_session(self, document_name, file_path, file_type, user_id=None):
        session_id = str(uuid.uuid4())
        session_data = {
            'session_id': session_id,
            'document_name': document_name,
            'file_path': file_path,
            'file_type': file_type,
            'user_id': user_id,
            'created_at': datetime.now().isoformat(),
            'last_accessed': datetime.now().isoformat(),
            'chat_history': []
        }
        self.sessions[session_id] = session_data
        self.save_sessions()
        logger.info(f"Created session {session_id} for user {user_id}: {document_name}")
        return session_id

    def get_session(self, session_id):
        return self.sessions.get(session_id)

    def get_user_session(self, session_id, user_id):
        session = self.sessions.get(session_id)
        if session and session.get('user_id') == user_id:
            return session
        return None

    def get_all_sessions(self):
        return list(self.sessions.values())

    def get_user_sessions(self, user_id):
        user_sessions = [s for s in self.sessions.values() if s.get('user_id') == user_id]
        user_sessions.sort(key=lambda x: x.get('last_accessed', ''), reverse=True)
        return user_sessions

    def user_owns_session(self, session_id, user_id):
        session = self.sessions.get(session_id)
        return session and session.get('user_id') == user_id

    def session_exists(self, session_id):
        return session_id in self.sessions

    def delete_session(self, session_id):
        try:
            if session_id in self.sessions:
                session_data = self.sessions[session_id]
                file_path = session_data.get('file_path')

                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        logger.info(f"Deleted file: {file_path}")
                    except Exception as e:
                        logger.warning(f"Could not delete file {file_path}: {e}")

                del self.sessions[session_id]
                self.save_sessions()
                logger.info(f"Deleted session: {session_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")
            return False

    def update_last_accessed(self, session_id):
        if session_id in self.sessions:
            self.sessions[session_id]['last_accessed'] = datetime.now().isoformat()
            self.save_sessions()

    def get_session_file_path(self, session_id):
        session = self.sessions.get(session_id)
        return session.get('file_path') if session else None

    def add_chat_message(self, session_id, role, content):
        if session_id in self.sessions:
            message = {
                'role': role,
                'content': content,
                'timestamp': datetime.now().isoformat()
            }
            self.sessions[session_id].setdefault('chat_history', []).append(message)
            self.save_sessions()

    def get_chat_history(self, session_id):
        session = self.sessions.get(session_id)
        return session.get('chat_history', []) if session else []

    def clear_chat_history(self, session_id):
        if session_id in self.sessions:
            self.sessions[session_id]['chat_history'] = []
            self.save_sessions()
            return True
        return False

    def get_session_stats(self, user_id=None):
        if user_id:
            sessions = self.get_user_sessions(user_id)
        else:
            sessions = list(self.sessions.values())

        return {
            'total_sessions': len(sessions),
            'sessions_with_chat': len([s for s in sessions if s.get('chat_history')]),
            'total_messages': sum(len(s.get('chat_history', [])) for s in sessions)
        }

    def cleanup_old_sessions(self, days_old=30):
        cutoff_date = datetime.now() - timedelta(days=days_old)
        sessions_to_delete = []

        for session_id, session_data in self.sessions.items():
            try:
                last_accessed = datetime.fromisoformat(session_data.get('last_accessed', session_data.get('created_at')))
                if last_accessed < cutoff_date:
                    sessions_to_delete.append(session_id)
            except ValueError:
                sessions_to_delete.append(session_id)

        deleted_count = 0
        for session_id in sessions_to_delete:
            if self.delete_session(session_id):
                deleted_count += 1

        logger.info(f"Cleaned up {deleted_count} old sessions")
        return deleted_count

    def migrate_sessions_to_user(self, user_id, session_ids):
        migrated = 0
        for session_id in session_ids:
            if session_id in self.sessions:
                self.sessions[session_id]['user_id'] = user_id
                migrated += 1

        if migrated > 0:
            self.save_sessions()
            logger.info(f"Migrated {migrated} sessions to user {user_id}")

        return migrated
