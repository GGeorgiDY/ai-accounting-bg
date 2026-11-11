import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

DOC_TYPES = ("invoice", "credit_note", "debit_note", "proforma", "other")
POSTABLE_DOC_TYPES = ("invoice", "credit_note", "debit_note")
PAYMENT_METHODS = ("bank", "cash", "card", "other", "unknown")
DIRECTIONS = ("purchase", "sale", "unknown")


def _to_float(v: Any) -> float:
    """Толерантно парсване на числа: '1 234,56', '1.234,56 лв.', None -> 0."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if "," in s and "." in s:
        # последният разделител е десетичният
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _to_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


Num = Annotated[float, BeforeValidator(_to_float)]
Str = Annotated[str, BeforeValidator(_to_str)]


# ---------- Данни на документ (извлечени от AI, редактируеми от счетоводител) ----------

class Party(BaseModel):
    name: Str = ""
    eik: Str = ""
    vat_number: Str = ""
    country: Str = ""


class Line(BaseModel):
    description: Str = ""
    quantity: Num = 0
    unit: Str = ""
    unit_price: Num = 0
    net_amount: Num = 0
    vat_rate: Num = 0
    vat_amount: Num = 0
    account_code: Str = ""


class Totals(BaseModel):
    net_amount: Num = 0
    vat_amount: Num = 0
    gross_amount: Num = 0


class DocumentData(BaseModel):
    document_type: Str = "invoice"
    document_number: Str = ""
    issue_date: Str = ""
    tax_event_date: Str = ""
    due_date: Str = ""
    currency: Str = ""
    exchange_rate: float | None = None
    payment_method: Str = "unknown"
    direction: Str = "unknown"
    supplier: Party = Field(default_factory=Party)
    customer: Party = Field(default_factory=Party)
    lines: list[Line] = Field(default_factory=list)
    totals: Totals = Field(default_factory=Totals)
    confidence: Num = 0
    notes: Str = ""

    @field_validator("supplier", "customer", "totals", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return {} if v is None else v

    @field_validator("lines", mode="before")
    @classmethod
    def _none_to_list(cls, v):
        return [] if v is None else v


# ---------- Компании ----------

class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    eik: str = Field(pattern=r"^\d{9}(\d{4})?$")
    vat_number: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=500)
    activity: str | None = Field(default=None, max_length=500)
    ai_prompt: str = ""
    allowed_accounts: list[str] = Field(default_factory=list)

    @field_validator("vat_number")
    @classmethod
    def _vat(cls, v):
        if not v:
            return None
        v = re.sub(r"\s", "", v).upper()
        if not re.fullmatch(r"[A-Z]{2}[0-9A-Z]{2,13}", v):
            raise ValueError("Невалиден ДДС номер (пример: BG123456789)")
        return v


class CompanyStats(BaseModel):
    total: int = 0
    queued: int = 0
    needs_review: int = 0
    failed: int = 0
    done: int = 0


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    eik: str
    vat_number: str | None
    address: str | None
    activity: str | None
    ai_prompt: str
    allowed_accounts: list[str]
    created_at: datetime
    stats: CompanyStats = Field(default_factory=CompanyStats)


# ---------- Документи ----------

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    original_filename: str
    size_bytes: int
    status: str
    attempts: int
    error: str | None
    direction: str | None
    doc_type: str | None
    doc_number: str | None
    issue_date: date | None
    counterparty_name: str | None
    currency: str | None
    net_amount: Decimal | None
    vat_amount: Decimal | None
    gross_amount: Decimal | None
    warnings: list
    created_at: datetime
    processed_at: datetime | None


class DocumentDetail(DocumentOut):
    extracted: dict | None
    journal: list | None
    raw_text: str | None
    used_ocr: bool | None
    llm_model: str | None
