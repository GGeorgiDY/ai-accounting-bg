import hashlib
import logging
import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import case, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import chart_of_accounts as coa
from app.config import settings
from app.db import get_db
from app.models import Company, DocStatus, Document
from app.schemas import CompanyIn, CompanyOut, CompanyStats, DocumentData, DocumentDetail, DocumentOut
from app.services import llm
from app.services.extraction import DEFAULT_PROMPT_TEMPLATE
from app.services.normalize import finalize
from app.services.processing import apply_result
from app.services.xml_export import ExportError, build_export

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# ---------------- helpers ----------------

def _company_or_404(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(404, "Компанията не е намерена")
    return company


def _document_or_404(db: Session, document_id: int) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Документът не е намерен")
    return doc


def _stats(db: Session, company_ids: list[int]) -> dict[int, CompanyStats]:
    if not company_ids:
        return {}
    s = Document.status
    rows = db.execute(
        select(
            Document.company_id,
            func.count(),
            func.sum(case((s.in_([DocStatus.QUEUED, DocStatus.PROCESSING]), 1), else_=0)),
            func.sum(case((s == DocStatus.NEEDS_REVIEW, 1), else_=0)),
            func.sum(case((s == DocStatus.FAILED, 1), else_=0)),
            func.sum(case((s.in_(DocStatus.EXPORTABLE), 1), else_=0)),
        )
        .where(Document.company_id.in_(company_ids))
        .group_by(Document.company_id)
    ).all()
    return {
        r[0]: CompanyStats(total=r[1], queued=r[2] or 0, needs_review=r[3] or 0, failed=r[4] or 0, done=r[5] or 0)
        for r in rows
    }


def _company_out(db: Session, company: Company) -> CompanyOut:
    out = CompanyOut.model_validate(company)
    out.stats = _stats(db, [company.id]).get(company.id, CompanyStats())
    return out


def _validate_accounts(codes: list[str]) -> list[str]:
    valid = {a.code for a in coa.line_accounts()}
    bad = [c for c in codes if c not in valid]
    if bad:
        raise HTTPException(422, f"Невалидни сметки за контиране: {', '.join(bad)}")
    return sorted(set(codes))


# ---------------- system ----------------

@router.get("/health/live")
def live():
    return {"status": "ok"}


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    queue = dict(
        db.execute(
            select(Document.status, func.count())
            .where(Document.status.in_([DocStatus.QUEUED, DocStatus.PROCESSING]))
            .group_by(Document.status)
        ).all()
    )
    return {"status": "ok", "llm": llm.status(), "queue": queue, "book_currency": settings.book_currency}


@router.get("/accounts")
def accounts():
    return [a.to_dict() for a in coa.CHART]


@router.get("/prompt-template")
def prompt_template():
    return {"template": DEFAULT_PROMPT_TEMPLATE}


# ---------------- companies ----------------

@router.get("/companies", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    companies = db.scalars(select(Company).order_by(Company.name)).all()
    stats = _stats(db, [c.id for c in companies])
    result = []
    for c in companies:
        out = CompanyOut.model_validate(c)
        out.stats = stats.get(c.id, CompanyStats())
        result.append(out)
    return result


@router.post("/companies", response_model=CompanyOut, status_code=201)
def create_company(body: CompanyIn, db: Session = Depends(get_db)):
    data = body.model_dump()
    data["allowed_accounts"] = _validate_accounts(body.allowed_accounts)
    company = Company(**data)
    db.add(company)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Вече има компания с този ЕИК")
    return _company_out(db, company)


@router.get("/companies/{company_id}", response_model=CompanyOut)
def get_company(company_id: int, db: Session = Depends(get_db)):
    return _company_out(db, _company_or_404(db, company_id))


@router.put("/companies/{company_id}", response_model=CompanyOut)
def update_company(company_id: int, body: CompanyIn, db: Session = Depends(get_db)):
    company = _company_or_404(db, company_id)
    data = body.model_dump()
    data["allowed_accounts"] = _validate_accounts(body.allowed_accounts)
    for k, v in data.items():
        setattr(company, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Вече има компания с този ЕИК")
    return _company_out(db, company)


@router.delete("/companies/{company_id}", status_code=204)
def delete_company(company_id: int, db: Session = Depends(get_db)):
    company = _company_or_404(db, company_id)
    paths = [d.stored_path for d in company.documents]
    db.delete(company)
    db.commit()
    for p in paths:
        Path(p).unlink(missing_ok=True)


# ---------------- documents ----------------

@router.get("/companies/{company_id}/documents", response_model=list[DocumentOut])
def list_documents(company_id: int, status: str | None = None, db: Session = Depends(get_db)):
    _company_or_404(db, company_id)
    q = select(Document).where(Document.company_id == company_id)
    if status:
        q = q.where(Document.status == status)
    return db.scalars(q.order_by(Document.id.desc())).all()


@router.post("/companies/{company_id}/documents", status_code=201)
async def upload_documents(company_id: int, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    _company_or_404(db, company_id)
    target_dir = Path(settings.upload_dir) / str(company_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.max_upload_mb * 1024 * 1024

    results = []
    for f in files:
        name = Path(f.filename or "document.pdf").name
        content = await f.read()
        if not content.startswith(b"%PDF"):
            results.append({"filename": name, "error": "Файлът не е PDF"})
            continue
        if len(content) > max_bytes:
            results.append({"filename": name, "error": f"Файлът е над {settings.max_upload_mb} MB"})
            continue
        sha = hashlib.sha256(content).hexdigest()
        existing = db.scalar(select(Document).where(Document.company_id == company_id, Document.sha256 == sha))
        if existing:
            results.append({"filename": name, "error": f"Вече е качен (документ #{existing.id})"})
            continue
        path = target_dir / f"{sha}.pdf"
        path.write_bytes(content)
        doc = Document(company_id=company_id, original_filename=name, stored_path=str(path),
                       sha256=sha, size_bytes=len(content), status=DocStatus.QUEUED, warnings=[])
        db.add(doc)
        db.flush()
        results.append({"filename": name, "document_id": doc.id})
    db.commit()
    return {"results": results}


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def get_document(document_id: int, db: Session = Depends(get_db)):
    return _document_or_404(db, document_id)


@router.get("/documents/{document_id}/file")
def get_document_file(document_id: int, db: Session = Depends(get_db)):
    doc = _document_or_404(db, document_id)
    return FileResponse(doc.stored_path, media_type="application/pdf",
                        content_disposition_type="inline", filename=doc.original_filename)


@router.put("/documents/{document_id}/data", response_model=DocumentDetail)
def update_document_data(document_id: int, body: DocumentData, db: Session = Depends(get_db)):
    """Счетоводителят коригира данните -> преизчисляване на статиите."""
    doc = _document_or_404(db, document_id)
    if doc.status in (DocStatus.QUEUED, DocStatus.PROCESSING):
        raise HTTPException(409, "Документът се обработва в момента")
    apply_result(doc, doc.company, finalize(doc.company, body, from_llm=False))
    db.commit()
    return doc


@router.post("/documents/{document_id}/approve", response_model=DocumentDetail)
def approve_document(document_id: int, db: Session = Depends(get_db)):
    doc = _document_or_404(db, document_id)
    if not doc.journal or doc.status not in (DocStatus.PROCESSED, DocStatus.NEEDS_REVIEW):
        raise HTTPException(409, "Документът няма счетоводни статии и не може да бъде одобрен")
    if not doc.issue_date:
        raise HTTPException(409, "Въведете дата на документа преди одобрение")
    doc.status = DocStatus.APPROVED
    try:
        build_export(doc.company, [doc])
    except ExportError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    db.commit()
    return doc


@router.post("/documents/{document_id}/reprocess", response_model=DocumentDetail)
def reprocess_document(document_id: int, db: Session = Depends(get_db)):
    doc = _document_or_404(db, document_id)
    if doc.status == DocStatus.PROCESSING:
        raise HTTPException(409, "Документът се обработва в момента")
    doc.status = DocStatus.QUEUED
    doc.attempts = 0
    doc.error = None
    doc.raw_text = None  # повторно извличане на текста (напр. след промяна на OCR)
    db.commit()
    return doc


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int, db: Session = Depends(get_db)):
    doc = _document_or_404(db, document_id)
    path = doc.stored_path
    db.delete(doc)
    db.commit()
    Path(path).unlink(missing_ok=True)


# ---------------- XML ----------------

def _xml_response(content: bytes, filename: str) -> Response:
    return Response(content, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/documents/{document_id}/xml")
def document_xml(document_id: int, db: Session = Depends(get_db)):
    doc = _document_or_404(db, document_id)
    try:
        content = build_export(doc.company, [doc])
    except ExportError as exc:
        raise HTTPException(409, str(exc))
    number = re.sub(r"[^\w\-]", "_", doc.doc_number or str(doc.id))
    return _xml_response(content, f"{doc.company.eik}_{doc.direction}_{number}.xml")


@router.get("/companies/{company_id}/export.xml")
def export_company(
    company_id: int,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    include_unreviewed: bool = False,
    db: Session = Depends(get_db),
):
    company = _company_or_404(db, company_id)
    statuses = list(DocStatus.EXPORTABLE) + ([DocStatus.NEEDS_REVIEW] if include_unreviewed else [])
    q = select(Document).where(Document.company_id == company_id, Document.status.in_(statuses))
    if date_from:
        q = q.where(Document.issue_date >= date_from)
    if date_to:
        q = q.where(Document.issue_date <= date_to)
    docs = db.scalars(q.order_by(Document.issue_date, Document.id)).all()

    exportable = []
    for doc in docs:
        try:
            build_export(company, [doc])
            exportable.append(doc)
        except ExportError:
            log.info("Skipping document #%d from export (not exportable)", doc.id)
    try:
        content = build_export(company, exportable,
                               date_from.isoformat() if date_from else None,
                               date_to.isoformat() if date_to else None)
    except ExportError as exc:
        raise HTTPException(409, str(exc))
    suffix = f"{date_from or 'start'}_{date_to or 'end'}"
    return _xml_response(content, f"{company.eik}_export_{suffix}.xml")
