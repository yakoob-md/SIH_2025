import os
import logging
import fitz  # PyMuPDF
import pdfplumber
import pytesseract
from PIL import Image
from docx import Document
import tiktoken
import nltk
from nltk.tokenize import sent_tokenize
from typing import List, Dict, Tuple
import io

# Download required NLTK data
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)

logger = logging.getLogger(__name__)

class DocumentParser:
    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100, ocr_threshold: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.ocr_threshold = ocr_threshold
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
    
    def parse_document(self, file_path: str, file_type: str) -> str:
        """Parse document based on file type and return extracted text."""
        try:
            if file_type.lower() == 'pdf':
                return self._parse_pdf(file_path)
            elif file_type.lower() in ['docx', 'doc']:
                return self._parse_docx(file_path)
            elif file_type.lower() == 'txt':
                return self._parse_txt(file_path)
            else:
                raise ValueError(f"Unsupported file type: {file_type}")
        except Exception as e:
            logger.error(f"Error parsing document {file_path}: {str(e)}")
            raise
    
    def _parse_pdf(self, file_path: str) -> str:
        """Parse PDF with hybrid text extraction and OCR."""
        full_text = ""
        
        try:
            # First attempt with pdfplumber for text extraction
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    try:
                        page_text = page.extract_text() or ""
                        
                        # If page has minimal text, try OCR
                        if len(page_text.strip()) < self.ocr_threshold:
                            logger.info(f"Page {page_num + 1} has minimal text, applying OCR")
                            page_text = self._ocr_pdf_page(file_path, page_num)
                        
                        full_text += page_text + "\n"
                    except Exception as e:
                        logger.warning(f"Error processing page {page_num + 1}: {str(e)}")
                        continue
                        
        except Exception as e:
            logger.warning(f"pdfplumber failed, trying PyMuPDF: {str(e)}")
            # Fallback to PyMuPDF
            full_text = self._parse_pdf_pymupdf(file_path)
        
        return full_text.strip()
    
    def _parse_pdf_pymupdf(self, file_path: str) -> str:
        """Fallback PDF parsing with PyMuPDF."""
        full_text = ""
        
        try:
            pdf_document = fitz.open(file_path)
            for page_num in range(pdf_document.page_count):
                try:
                    page = pdf_document[page_num]
                    page_text = page.get_text()
                    
                    # Apply OCR if minimal text
                    if len(page_text.strip()) < self.ocr_threshold:
                        page_text = self._ocr_pdf_page(file_path, page_num)
                    
                    full_text += page_text + "\n"
                except Exception as e:
                    logger.warning(f"Error processing page {page_num + 1} with PyMuPDF: {str(e)}")
                    continue
                    
            pdf_document.close()
        except Exception as e:
            logger.error(f"PyMuPDF parsing failed: {str(e)}")
            raise
            
        return full_text.strip()
    
    def _ocr_pdf_page(self, file_path: str, page_num: int) -> str:
        """Apply OCR to a specific PDF page."""
        try:
            # Convert PDF page to image using PyMuPDF
            pdf_document = fitz.open(file_path)
            page = pdf_document[page_num]
            
            # Render page to image
            mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better OCR quality
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            
            # OCR the image
            image = Image.open(io.BytesIO(img_data))
            ocr_text = pytesseract.image_to_string(image, config='--psm 6')
            
            pdf_document.close()
            return ocr_text
            
        except Exception as e:
            logger.warning(f"OCR failed for page {page_num + 1}: {str(e)}")
            return ""
    
    def _parse_docx(self, file_path: str) -> str:
        """Parse DOCX file."""
        try:
            doc = Document(file_path)
            full_text = []
            
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    full_text.append(paragraph.text)
            
            return "\n".join(full_text)
            
        except Exception as e:
            logger.error(f"Error parsing DOCX file: {str(e)}")
            raise
    
    def _parse_txt(self, file_path: str) -> str:
        """Parse text file with encoding detection."""
        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as file:
                    return file.read()
            except UnicodeDecodeError:
                continue
                
        raise ValueError("Could not decode text file with any supported encoding")
    
    def chunk_text(self, text: str) -> List[Dict[str, any]]:
        """Chunk text into semantic segments with token limits."""
        if not text.strip():
            return []
        
        # Split into sentences
        sentences = sent_tokenize(text)
        chunks = []
        current_chunk = ""
        current_tokens = 0
        
        for sentence in sentences:
            sentence_tokens = len(self.tokenizer.encode(sentence))
            
            # If adding this sentence would exceed chunk size, save current chunk
            if current_tokens + sentence_tokens > self.chunk_size and current_chunk:
                chunks.append({
                    'text': current_chunk.strip(),
                    'token_count': current_tokens,
                    'chunk_id': len(chunks)
                })
                
                # Start new chunk with overlap
                overlap_text = self._get_overlap_text(current_chunk, self.chunk_overlap)
                current_chunk = overlap_text + " " + sentence
                current_tokens = len(self.tokenizer.encode(current_chunk))
            else:
                # Add sentence to current chunk
                current_chunk += " " + sentence if current_chunk else sentence
                current_tokens += sentence_tokens
        
        # Add final chunk
        if current_chunk.strip():
            chunks.append({
                'text': current_chunk.strip(),
                'token_count': current_tokens,
                'chunk_id': len(chunks)
            })
        
        logger.info(f"Created {len(chunks)} chunks from text")
        return chunks
    
    def _get_overlap_text(self, text: str, overlap_tokens: int) -> str:
        """Get the last N tokens worth of text for overlap."""
        if overlap_tokens <= 0:
            return ""
        
        tokens = self.tokenizer.encode(text)
        if len(tokens) <= overlap_tokens:
            return text
        
        overlap_token_ids = tokens[-overlap_tokens:]
        return self.tokenizer.decode(overlap_token_ids)
    
    def get_file_info(self, file_path: str) -> Dict[str, any]:
        """Get basic file information."""
        stat = os.stat(file_path)
        return {
            'file_size': stat.st_size,
            'file_size_mb': round(stat.st_size / (1024 * 1024), 2),
            'file_name': os.path.basename(file_path)
        }