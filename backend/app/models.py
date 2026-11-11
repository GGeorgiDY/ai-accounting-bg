from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocStatus:
    QUEUED = "queued"            # чака обработка
    PROCESSING = "processing"    # в момента се обработва от worker
    PROCESSED = "processed"      # обработен без забележки
    NEEDS_REVIEW = "needs_review"  # обработен, но има предупреждения
    APPROVED = "approved"        # одобрен от счетоводител
    FAILED = "failed"            # грешка

    EXPORTABLE = (PROCESSED, APPROVED)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    eik: Mapped[str] = mapped_column(String(13), unique=True)
    vat_number: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(500))
    activity: Mapped[str | None] = mapped_column(String(500))
    # Промпт/профил, който описва какви документи се очакват за фирмата
    ai_prompt: Mapped[str] = mapped_column(Text, default="")
    # Позволени сметки за контиране (празно = целият сметкоплан)
    allowed_accounts: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("company_id", "sha256", name="uq_document_company_sha"),
        Index("ix_documents_status", "status"),
        Index("ix_documents_company_date", "company_id", "issue_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    original_filename: Mapped[str] = mapped_column(String(500))
    stored_path: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(20), default=DocStatus.QUEUED)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)

    # Денормализирани полета за списъци/филтри
    direction: Mapped[str | None] = mapped_column(String(10))  # purchase | sale | unknown
    doc_type: Mapped[str | None] = mapped_column(String(20))
    doc_number: Mapped[str | None] = mapped_column(String(100))
    issue_date: Mapped[date | None] = mapped_column(Date)
    counterparty_name: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str | None] = mapped_column(String(3))
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    vat_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    gross_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    # Пълни данни
    raw_text: Mapped[str | None] = mapped_column(Text)
    used_ocr: Mapped[bool | None] = mapped_column(default=None)
    llm_raw: Mapped[dict | None] = mapped_column(JSON)     # суровият отговор на модела (одит)
    extracted: Mapped[dict | None] = mapped_column(JSON)   # нормализирани/редактирани данни
    journal: Mapped[list | None] = mapped_column(JSON)     # счетоводни статии
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    llm_model: Mapped[str | None] = mapped_column(String(100))

    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    company: Mapped[Company] = relationship(back_populates="documents")
