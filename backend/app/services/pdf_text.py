"""PDF -> текст. Първо текстов слой (pdfplumber); ако липсва (сканиран документ) -> OCR."""
import logging
import re

import pdfplumber

from app.config import settings

log = logging.getLogger(__name__)

MIN_CHARS_PER_PAGE = 40


def _clean(text: str) -> str:
    text = text.replace("\x00", "").replace("\t", " ")
    # Големите хоризонтални празнини са граници между колони (напр. Доставчик | Получател).
    # Запазваме ги като " | ", за да не се слеят двете страни на фактурата в един ред.
    text = re.sub(r"(?<! ) {2}(?! )", " ", text)
    text = re.sub(r" {3,}", " | ", text)
    text = re.sub(r"(?m)^[ |]+|[ |]+$", "", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _ocr(path: str) -> str:
    import pytesseract
    from pdf2image import convert_from_path

    pages = convert_from_path(path, dpi=300, first_page=1, last_page=10)
    return "\n\n".join(
        f"--- Страница {i} ---\n" + pytesseract.image_to_string(img, lang=settings.ocr_lang)
        for i, img in enumerate(pages, start=1)
    )


def extract_text(path: str) -> tuple[str, bool]:
    """Връща (текст, използван_ли_е_OCR)."""
    with pdfplumber.open(path) as pdf:
        page_texts = [p.extract_text(layout=True) or "" for p in pdf.pages[:10]]
        page_count = max(len(pdf.pages[:10]), 1)

    text = "\n\n".join(
        f"--- Страница {i} ---\n{t}" for i, t in enumerate(page_texts, start=1)
    )
    useful = len(re.sub(r"\s|-|Страница \d+", "", text))
    if useful >= MIN_CHARS_PER_PAGE * page_count:
        return _clean(text)[: settings.max_document_chars], False

    log.info("No text layer in %s, running OCR", path)
    return _clean(_ocr(path))[: settings.max_document_chars], True
