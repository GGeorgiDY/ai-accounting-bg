"""Pipeline: PDF -> текст -> LLM -> нормализация/проверки -> статии -> XML dry-run."""
import logging
from datetime import date, datetime, timezone

from app.config import settings
from app.models import Company, DocStatus, Document
from app.schemas import DocumentData
from app.services import extraction, llm, pdf_text
from app.services.normalize import Result, finalize
from app.services.xml_export import ExportError, build_export

log = logging.getLogger(__name__)


def apply_result(doc: Document, company: Company, result: Result) -> None:
    data = result.data
    other = data.supplier if result.direction == "purchase" else data.customer
    doc.extracted = data.model_dump()
    doc.journal = result.journal
    doc.direction = result.direction
    doc.doc_type = data.document_type
    doc.doc_number = data.document_number[:100] or None
    doc.issue_date = date.fromisoformat(data.issue_date) if data.issue_date else None
    doc.counterparty_name = (other.name or None) if result.direction != "unknown" else None
    doc.currency = data.currency
    doc.net_amount = data.totals.net_amount
    doc.vat_amount = data.totals.vat_amount
    doc.gross_amount = data.totals.gross_amount

    warnings = list(result.warnings)
    if result.journal:
        try:  # гарантираме, че документът ще мине XSD валидацията при експорт
            doc.status = DocStatus.PROCESSED
            build_export(company, [doc])
        except ExportError as exc:
            warnings.append(str(exc))
    doc.warnings = warnings
    doc.error = None
    doc.status = DocStatus.NEEDS_REVIEW if (warnings or not result.journal) else DocStatus.PROCESSED
    doc.processed_at = datetime.now(timezone.utc)


def process_document(doc: Document) -> None:
    company = doc.company
    if not doc.raw_text:
        doc.raw_text, doc.used_ocr = pdf_text.extract_text(doc.stored_path)
    if len(doc.raw_text.strip()) < 20:
        raise ValueError("Не е открит текст в документа (празен или нечетлив PDF).")

    raw = llm.chat_json(
        system=extraction.build_system_prompt(company),
        user=extraction.build_user_prompt(doc.original_filename, doc.raw_text),
        schema=extraction.build_schema(company),
    )
    doc.llm_raw = raw
    doc.llm_model = settings.llm_model
    data = DocumentData.model_validate(raw)
    apply_result(doc, company, finalize(company, data, from_llm=True))
