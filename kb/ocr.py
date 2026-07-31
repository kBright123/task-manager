import logging

import pypdfium2 as pdfium
from rapidocr import RapidOCR

from .config import KB_OCR_DPI_SCALE

logger = logging.getLogger(__name__)

logging.getLogger('RapidOCR').setLevel(logging.WARNING)

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        logger.info('loading RapidOCR engine...')
        _engine = RapidOCR()
    return _engine


def ocr_image(pil_image):
    import numpy as np
    arr = np.array(pil_image.convert('RGB'))
    result = _get_engine()(arr)
    if result is None:
        return ''
    return '\n'.join(t for t in result.txts if t and t.strip())


def render_pdf_pages(pdf_path):
    pdf = pdfium.PdfDocument(pdf_path)
    n = len(pdf)
    for page_no in range(n):
        page = pdf[page_no]
        image = page.render(scale=KB_OCR_DPI_SCALE).to_pil()
        yield page_no + 1, image
    pdf.close()


def ocr_file(file_path):
    lower = file_path.lower()
    pages = []
    if lower.endswith('.pdf'):
        for page_no, image in render_pdf_pages(file_path):
            pages.append((page_no, ocr_image(image)))
    else:
        from PIL import Image
        image = Image.open(file_path)
        image.load()
        pages.append((1, ocr_image(image)))
    return pages
