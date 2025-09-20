import os
import json
import logging
import numpy as np
import faiss
from openai import OpenAI
from typing import List, Dict, Tuple, Optional
import pickle

logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self, openai_client: OpenAI, embedding_model: str = "text-embedding-3-small", 
                 embeddings_folder: str = "embeddings"):
        self.openai_client = openai_client
        self.embedding_model = embedding_model
        self.embeddings_folder = embeddings_folder
        self.dimension = 1536  # text-embedding-3-small dimension
        
        # Create embeddings folder if it doesn't exist
        os.makedirs(self.embeddings_folder, exist_ok=True)
    
    def create_embeddings(self, chunks: List[Dict[str, any]], session_id: str) -> bool:
        """Create embeddings for text chunks and store in FAISS index."""
        try:
            if not chunks:
                logger.warning("No chunks provided for embedding creation")
                return False
            
            logger.info(f"Creating embeddings for {len(chunks)} chunks")
            
            # Extract text from chunks
            texts = [chunk['text'] for chunk in chunks]
            
            # Create embeddings in batches to avoid rate limits
            embeddings = []
            batch_size = 100  # Adjust based on rate limits
            
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i + batch_size]
                logger.info(f"Processing embedding batch {i//batch_size + 1}/{(len(texts) + batch_size - 1)//batch_size}")
                
                try:
                    response = self.openai_client.embeddings.create(
                        model=self.embedding_model,
                        input=batch_texts,
                        encoding_format="float"
                    )
                    
                    batch_embeddings = [data.embedding for data in response.data]
                    embeddings.extend(batch_embeddings)
                    
                except Exception as e:
                    logger.error(f"Error creating embeddings for batch: {str(e)}")
                    raise
            
            # Convert to numpy array
            embeddings_array = np.array(embeddings, dtype=np.float32)
            
            # Create FAISS index
            index = faiss.IndexFlatIP(self.dimension)  # Inner Product (cosine similarity)
            
            # Normalize embeddings for cosine similarity
            faiss.normalize_L2(embeddings_array)
            
            # Add embeddings to index
            index.add(embeddings_array)
            
            # Save index and metadata
            self._save_index(session_id, index, chunks)
            
            logger.info(f"Successfully created and saved FAISS index for session {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating embeddings: {str(e)}")
            raise
    
    def similarity_search(self, query: str, session_id: str, k: int = 5) -> List[Dict[str, any]]:
        """Perform similarity search and return top k relevant chunks."""
        try:
            # Load index and metadata
            index, chunks_metadata = self._load_index(session_id)
            
            if index is None or chunks_metadata is None:
                logger.error(f"No index found for session {session_id}")
                return []
            
            # Create embedding for query
            response = self.openai_client.embeddings.create(
                model=self.embedding_model,
                input=[query],
                encoding_format="float"
            )
            
            query_embedding = np.array([response.data[0].embedding], dtype=np.float32)
            
            # Normalize query embedding
            faiss.normalize_L2(query_embedding)
            
            # Search
            scores, indices = index.search(query_embedding, k)
            
            # Prepare results
            results = []
            for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
                if idx != -1:  # Valid index
                    chunk = chunks_metadata[idx].copy()
                    chunk['similarity_score'] = float(score)
                    chunk['rank'] = i + 1
                    results.append(chunk)
            
            logger.info(f"Found {len(results)} relevant chunks for query")
            return results
            
        except Exception as e:
            logger.error(f"Error performing similarity search: {str(e)}")
            return []
    
    def _save_index(self, session_id: str, index: faiss.Index, chunks_metadata: List[Dict[str, any]]):
        """Save FAISS index and metadata to disk."""
        try:
            session_folder = os.path.join(self.embeddings_folder, session_id)
            os.makedirs(session_folder, exist_ok=True)
            
            # Save FAISS index
            index_path = os.path.join(session_folder, "faiss_index.bin")
            faiss.write_index(index, index_path)
            
            # Save metadata
            metadata_path = os.path.join(session_folder, "chunks_metadata.pkl")
            with open(metadata_path, 'wb') as f:
                pickle.dump(chunks_metadata, f)
            
            # Save session info
            info_path = os.path.join(session_folder, "session_info.json")
            session_info = {
                'session_id': session_id,
                'num_chunks': len(chunks_metadata),
                'embedding_model': self.embedding_model,
                'index_dimension': self.dimension
            }
            
            with open(info_path, 'w') as f:
                json.dump(session_info, f, indent=2)
                
            logger.info(f"Saved index and metadata for session {session_id}")
            
        except Exception as e:
            logger.error(f"Error saving index: {str(e)}")
            raise
    
    def _load_index(self, session_id: str) -> Tuple[Optional[faiss.Index], Optional[List[Dict[str, any]]]]:
        """Load FAISS index and metadata from disk."""
        try:
            session_folder = os.path.join(self.embeddings_folder, session_id)
            
            if not os.path.exists(session_folder):
                logger.warning(f"Session folder not found: {session_folder}")
                return None, None
            
            # Load FAISS index
            index_path = os.path.join(session_folder, "faiss_index.bin")
            if not os.path.exists(index_path):
                logger.warning(f"FAISS index not found: {index_path}")
                return None, None
            
            index = faiss.read_index(index_path)
            
            # Load metadata
            metadata_path = os.path.join(session_folder, "chunks_metadata.pkl")
            if not os.path.exists(metadata_path):
                logger.warning(f"Metadata not found: {metadata_path}")
                return None, None
            
            with open(metadata_path, 'rb') as f:
                chunks_metadata = pickle.load(f)
            
            logger.info(f"Loaded index for session {session_id} with {len(chunks_metadata)} chunks")
            return index, chunks_metadata
            
        except Exception as e:
            logger.error(f"Error loading index: {str(e)}")
            return None, None
    
    def session_exists(self, session_id: str) -> bool:
        """Check if a session has stored embeddings."""
        session_folder = os.path.join(self.embeddings_folder, session_id)
        index_path = os.path.join(session_folder, "faiss_index.bin")
        metadata_path = os.path.join(session_folder, "chunks_metadata.pkl")
        
        return os.path.exists(index_path) and os.path.exists(metadata_path)
    
    def get_session_info(self, session_id: str) -> Optional[Dict[str, any]]:
        """Get session information."""
        try:
            session_folder = os.path.join(self.embeddings_folder, session_id)
            info_path = os.path.join(session_folder, "session_info.json")
            
            if not os.path.exists(info_path):
                return None
            
            with open(info_path, 'r') as f:
                return json.load(f)
                
        except Exception as e:
            logger.error(f"Error getting session info: {str(e)}")
            return None
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session data."""
        try:
            session_folder = os.path.join(self.embeddings_folder, session_id)
            
            if os.path.exists(session_folder):
                import shutil
                shutil.rmtree(session_folder)
                logger.info(f"Deleted session {session_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error deleting session: {str(e)}")
            return False