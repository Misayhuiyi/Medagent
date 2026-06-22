"""
pdf_ocr.py — OCR pipeline for scanned PDFs using pypdfium2 + easyocr

No external dependencies (poppler/tesseract) needed.
pypdfium2 renders PDF pages, easyocr recognizes text (Chinese + English).
"""
import os
import sys
import json
import warnings
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional

warnings.filterwarnings('ignore')

def log(msg):
    """Print with flush for real-time output"""
    print(msg, flush=True)


def log_progress(current, total, msg=""):
    """Print progress on one line"""
    print(f"  [{current}/{total}] {msg}", flush=True)


def check_dependencies():
    """Check if required packages are installed"""
    try:
        import pypdfium2
        import easyocr
        import numpy as np
        from PIL import Image
        return True
    except ImportError as e:
        log(f"Missing dependency: {e}")
        log("Run: pip install pypdfium2 easyocr Pillow numpy")
        return False


class PDFOcrEngine:
    """OCR engine for scanned PDFs using pypdfium2 (rendering) + easyocr (recognition)"""

    def __init__(self, lang: List[str] = None, gpu: bool = False):
        """
        Args:
            lang: Language list for OCR. Default: ['ch_sim', 'en'] (Chinese + English)
            gpu: Use GPU if available
        """
        if lang is None:
            lang = ['ch_sim', 'en']
        self.lang = lang
        self.gpu = gpu
        self.reader = None

    def _get_reader(self):
        """Lazy-load easyocr reader (first call downloads model)"""
        if self.reader is None:
            log(f"Loading easyocr model (lang={self.lang})...")
            import easyocr
            self.reader = easyocr.Reader(self.lang, gpu=self.gpu)
            log("  OCR model loaded")
        return self.reader

    def ocr_pdf(self, pdf_path: str, dpi: int = 200,
                output_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        OCR a scanned PDF - render pages to images, then recognize text.

        Args:
            pdf_path: Path to scanned PDF
            dpi: Rendering resolution (higher = better OCR, slower)
            output_dir: If set, save page images and OCR text here

        Returns:
            List of chunks with OCR text, one per page
        """
        import pypdfium2 as pdfium
        from PIL import Image

        fname = os.path.basename(pdf_path)
        name_no_ext = os.path.splitext(fname)[0]
        log(f"\nOCR Processing: {fname}")

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        # Open PDF
        doc = pdfium.PdfDocument(pdf_path)
        num_pages = len(doc)
        log(f"  Pages: {num_pages}")

        reader = self._get_reader()
        all_chunks = []

        for page_idx in range(num_pages):
            # Render page to image
            page = doc[page_idx]
            bitmap = page.render(scale=dpi / 72)  # 72 = base DPI
            pil_image = bitmap.to_pil()

            # Save page image if output_dir set
            if output_dir:
                img_path = os.path.join(output_dir, f"{name_no_ext}_p{page_idx+1}.png")
                pil_image.save(img_path, "PNG")

            # OCR the image
            import numpy as np
            img_array = np.array(pil_image)
            results = reader.readtext(img_array)

            # Combine OCR results into text
            page_text_lines = []
            for (bbox, text, confidence) in results:
                if confidence > 0.3:  # Filter low-confidence results
                    page_text_lines.append(text)

            page_text = "\n".join(page_text_lines)

            if page_text.strip():
                all_chunks.append({
                    'text': page_text,
                    'source_file': fname,
                    'source_path': pdf_path,
                    'start_page': page_idx + 1,
                    'end_page': page_idx + 1,
                    'metadata': {'type': 'ocr_text', 'method': 'easyocr'}
                })

            # Progress
            if (page_idx + 1) % 10 == 0 or page_idx == num_pages - 1:
                log(f"  Page {page_idx+1}/{num_pages} done (chars: {len(page_text)})")

        doc.close()
        log(f"  OCR complete: {len(all_chunks)} pages with text")
        return all_chunks

    def ocr_and_save(self, pdf_path: str, output_json: str,
                     output_dir: Optional[str] = None, dpi: int = 200):
        """OCR a PDF and save results to JSON"""
        chunks = self.ocr_pdf(pdf_path, dpi=dpi, output_dir=output_dir)
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)
        log(f"Saved {len(chunks)} chunks to {output_json}")
        return chunks


def batch_ocr(pdf_list: List[str], output_dir: str = None, dpi: int = 200) -> List[Dict[str, Any]]:
    """OCR multiple PDFs and return all chunks"""
    engine = PDFOcrEngine()
    all_chunks = []
    for pdf_path in pdf_list:
        if not os.path.exists(pdf_path):
            log(f"Skipping (not found): {pdf_path}")
            continue
        try:
            chunks = engine.ocr_pdf(pdf_path, dpi=dpi, output_dir=output_dir)
            all_chunks.extend(chunks)
        except Exception as e:
            log(f"  FAILED: {e}")
    return all_chunks


def add_ocr_to_rag(chunks: List[Dict], db_path: str = None, collection: str = 'lung_cancer_guidelines'):
    """Add OCR text chunks to existing ChromaDB"""
    from sentence_transformers import SentenceTransformer
    import chromadb

    if db_path is None:
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               '..', 'folder-rag', 'database', 'chroma_db')

    # Load model
    log(f"\nLoading embedding model...")
    model = 'BAAI/bge-small-zh-v1.5'
    embed_fn = SentenceTransformer(model, device='cpu')

    # Open existing DB
    client = chromadb.PersistentClient(path=db_path)
    try:
        col = client.get_or_create_collection(collection)
    except:
        col = client.create_collection(collection)

    log(f"Existing collection: {col.count()} docs")

    # Add in batches
    batch_size = 100
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        texts = [c['text'] for c in batch]
        metas = [{'source_file': c.get('source_file',''), 'source_path': c.get('source_path',''),
                  'start_page': c.get('start_page',0), 'end_page': c.get('end_page',0),
                  'type': 'ocr'} for c in batch]
        embeds = embed_fn.encode(texts, normalize_embeddings=True).tolist()
        ids = [f'ocr_{i+j}' for j in range(len(batch))]
        col.add(ids=ids, embeddings=embeds, documents=texts, metadatas=metas)
        bn = i // batch_size + 1
        total = (len(chunks) - 1) // batch_size + 1
        log(f"  Batch {bn}/{total} added ({col.count()} total)")

    log(f"Done! Collection now: {col.count()} docs")
    return col.count()


# Default scanned PDFs in the lung cancer knowledge base
DEFAULT_SCANNED_PDFS = [
    r'\\Steven\Agent\智能体\开发任务\医生Agent\知识库\临床指南\CSCO\CSCO 2016-2026（缺2015、2017）\2019 CSCO_LC.pdf',
    r'\\Steven\Agent\智能体\开发任务\医生Agent\知识库\临床指南\CSCO\CSCO 2016-2026（缺2015、2017）\2019 CSCO_irAEs.pdf',
    r'\\Steven\Agent\智能体\开发任务\医生Agent\知识库\临床指南\CSCO\CSCO 2016-2026（缺2015、2017）\2023 CSCO_NSCLC.pdf',
    r'\\Steven\Agent\智能体\开发任务\医生Agent\知识库\临床指南\CSCO\CSCO 2016-2026（缺2015、2017）\2025 CSCO_ICI.pdf',
    r'\\Steven\Agent\智能体\开发任务\医生Agent\知识库\临床指南\NCCN\2025_NSCLC.pdf',
    r'\\Steven\Agent\智能体\开发任务\医生Agent\知识库\临床指南\NCCN\2026_NSCLC Version4.pdf',
]


def main():
    import argparse
    parser = argparse.ArgumentParser(description='OCR scanned PDFs and add to RAG')
    parser.add_argument('--file', help='Single PDF to OCR')
    parser.add_argument('--all', action='store_true', help='OCR all 6 default scanned PDFs')
    parser.add_argument('--dpi', type=int, default=200, help='Rendering DPI')
    parser.add_argument('--no_rag', action='store_true', help='OCR only, skip adding to RAG')
    parser.add_argument('--output_dir', default=None, help='Save page images here')

    args = parser.parse_args()

    if not check_dependencies():
        return

    # Determine which PDFs to process
    pdfs_to_process = []
    if args.file:
        pdfs_to_process = [args.file]
    elif args.all:
        pdfs_to_process = DEFAULT_SCANNED_PDFS
    else:
        # Default: process all 6
        pdfs_to_process = DEFAULT_SCANNED_PDFS

    # Run OCR
    engine = PDFOcrEngine()
    all_chunks = []
    for pdf_path in pdfs_to_process:
        if not os.path.exists(pdf_path):
            log(f"Skipping (not found): {pdf_path}")
            continue
        size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        log(f"\n{'='*50}")
        log(f"OCR: {os.path.basename(pdf_path)} ({size_mb:.0f}MB)")
        log(f"{'='*50}")
        try:
            chunks = engine.ocr_pdf(pdf_path, dpi=args.dpi, output_dir=args.output_dir)
            all_chunks.extend(chunks)
        except Exception as e:
            log(f"  FAILED: {e}")

    log(f"\nTotal OCR chunks: {len(all_chunks)}")

    if not args.no_rag and all_chunks:
        log(f"\nAdding to RAG database...")
        add_ocr_to_rag(all_chunks)
    elif args.no_rag:
        # Save to JSON
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ocr_chunks.json')
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(all_chunks, f, ensure_ascii=False)
        log(f"Saved OCR chunks to: {out}")


if __name__ == '__main__':
    main()
