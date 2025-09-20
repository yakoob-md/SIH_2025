import logging
from openai import OpenAI
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ChatEngine:
    def __init__(self, openai_client: OpenAI, chat_model: str = "gpt-4o-mini"):
        self.openai_client = openai_client
        self.chat_model = chat_model
        self.system_prompt = """You are a helpful AI assistant that answers questions based on the provided document context. 

Instructions:
1. Use ONLY the information provided in the context to answer questions
2. If the context doesn't contain enough information to answer the question, say so clearly
3. Be concise but comprehensive in your responses
4. If you need to make inferences, make it clear what is directly stated vs. what you're inferring
5. Cite specific parts of the context when possible by mentioning relevant sections
6. If the question is not related to the document content, politely redirect the user
7. Understand the prompt well and cpature the nuances and answer accordingly
8. If the question is not in english but in some other language, respond in the same language itself

Context will be provided as numbered sections below."""

    def generate_response(self, query: str, relevant_chunks: List[Dict[str, Any]], 
                         conversation_history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        """Generate a response based on query and relevant document chunks."""
        try:
            if not relevant_chunks:
                return {
                    'response': "I don't have any relevant context to answer your question. Please make sure you've uploaded a document and that your question relates to the document content.",
                    'sources_used': 0,
                    'confidence': 'low'
                }
            
            # Prepare context from relevant chunks
            context = self._prepare_context(relevant_chunks)
            
            # Build conversation messages
            messages = self._build_messages(query, context, conversation_history)
            
            # Generate response
            response = self.openai_client.chat.completions.create(
                model=self.chat_model,
                messages=messages,
                temperature=0.3,  # Lower temperature for more factual responses
                max_tokens=1000,
                top_p=0.9
            )
            
            response_text = response.choices[0].message.content
            
            # Calculate confidence based on similarity scores
            confidence = self._calculate_confidence(relevant_chunks)
            
            result = {
                'response': response_text,
                'sources_used': len(relevant_chunks),
                'confidence': confidence,
                'relevant_chunks': [
                    {
                        'chunk_id': chunk['chunk_id'],
                        'similarity_score': chunk['similarity_score'],
                        'text_preview': chunk['text'][:200] + "..." if len(chunk['text']) > 200 else chunk['text']
                    }
                    for chunk in relevant_chunks
                ],
                'usage': {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens
                }
            }
            
            logger.info(f"Generated response using {len(relevant_chunks)} chunks, {result['usage']['total_tokens']} tokens")
            return result
            
        except Exception as e:
            logger.error(f"Error generating response: {str(e)}")
            return {
                'response': f"I encountered an error while processing your question: {str(e)}",
                'sources_used': 0,
                'confidence': 'error',
                'error': str(e)
            }
    
    def _prepare_context(self, relevant_chunks: List[Dict[str, Any]]) -> str:
        """Prepare context string from relevant chunks."""
        context_parts = []
        
        for i, chunk in enumerate(relevant_chunks, 1):
            # Add chunk with section numbering and similarity info
            context_parts.append(
                f"--- Section {i} (Relevance: {chunk['similarity_score']:.3f}) ---\n"
                f"{chunk['text']}\n"
            )
        
        return "\n".join(context_parts)
    
    def _build_messages(self, query: str, context: str, 
                       conversation_history: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
        """Build the conversation messages for the chat completion."""
        messages = [{"role": "system", "content": self.system_prompt}]
        
        # Add conversation history if provided
        if conversation_history:
            messages.extend(conversation_history)
        
        # Add current query with context
        user_message = f"Context from the document:\n\n{context}\n\nUser Question: {query}"
        messages.append({"role": "user", "content": user_message})
        
        return messages
    
    def _calculate_confidence(self, relevant_chunks: List[Dict[str, Any]]) -> str:
        """Calculate confidence level based on similarity scores."""
        if not relevant_chunks:
            return 'low'
        
        avg_score = sum(chunk['similarity_score'] for chunk in relevant_chunks) / len(relevant_chunks)
        max_score = max(chunk['similarity_score'] for chunk in relevant_chunks)
        
        # Confidence thresholds (these may need tuning based on your use case)
        if max_score > 0.85 and avg_score > 0.75:
            return 'high'
        elif max_score > 0.75 and avg_score > 0.65:
            return 'medium'
        else:
            return 'low'
    
    def validate_query(self, query: str) -> Dict[str, Any]:
        """Validate and preprocess user query."""
        if not query or not query.strip():
            return {
                'valid': False,
                'error': 'Query cannot be empty'
            }
        
        if len(query.strip()) < 3:
            return {
                'valid': False,
                'error': 'Query too short. Please provide a more detailed question.'
            }
        
        if len(query) > 1000:  # Reasonable limit
            return {
                'valid': False,
                'error': 'Query too long. Please keep questions under 1000 characters.'
            }
        
        return {
            'valid': True,
            'processed_query': query.strip()
        }
    
    def get_conversation_summary(self, conversation_history: List[Dict[str, str]]) -> str:
        """Generate a summary of the conversation history."""
        try:
            if not conversation_history or len(conversation_history) < 4:
                return ""
            
            # Prepare conversation for summarization
            convo_text = []
            for msg in conversation_history:
                role = msg['role'].capitalize()
                convo_text.append(f"{role}: {msg['content']}")
            
            conversation_string = "\n".join(convo_text)
            
            summary_prompt = f"""Please provide a brief summary of this conversation between a user and an AI assistant discussing a document. Focus on the main topics and questions asked:

{conversation_string}

Summary (2-3 sentences):"""
            
            response = self.openai_client.chat.completions.create(
                model=self.chat_model,
                messages=[{"role": "user", "content": summary_prompt}],
                temperature=0.3,
                max_tokens=150
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error generating conversation summary: {str(e)}")
            return ""