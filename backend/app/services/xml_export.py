"""Генериране на XML по схема urn:bg:accounting:export:v1 и валидация срещу XSD."""
import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from lxml import etree

from app import chart_of_accounts as coa
from app.config import settings
from app.models import Company, Document
from app.schemas import DocumentData
from app.services.accounting import d, q2

NS = "urn:bg:accounting:export:v1"
XSD_PATH = Path(__file__).resolve().parent.parent / "xml" / "accounting_export_v1.xsd"
SOFTWARE = "AccountantAI 0.1"


class ExportError(ValueError):
    pass


@lru_cache(maxsize=1)
def schema() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(XSD_PATH)))


def _sub(parent, tag: str, text=None, **attrs):
    el = etree.SubElement(parent, f"{{{NS}}}{tag}", {k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


def _amount(x) -> str:
    return str(q2(x))


def _decimal(x) -> str:
    v = d(x).normalize()
    return format(v, "f")


def _txt(s: str, limit: int) -> str:
    return (s or "").strip()[:limit]


def _add_document(parent, doc: Document) -> None:
    data = DocumentData.model_validate(doc.extracted)
    el = _sub(parent, "Document", id=doc.id, kind=data.document_type,
              direction=data.direction, status=doc.status)
    _sub(el, "Number", _txt(data.document_number, 255) or "б/н")
    _sub(el, "IssueDate", data.issue_date)
    if data.tax_event_date:
        _sub(el, "TaxEventDate", data.tax_event_date)
    if data.due_date:
        _sub(el, "DueDate", data.due_date)
    _sub(el, "Currency", data.currency)
    _sub(el, "ExchangeRate", format(d(data.exchange_rate).quantize(Decimal("0.0000000001")).normalize(), "f"))
    _sub(el, "PaymentMethod", data.payment_method)

    party, role = (data.supplier, "supplier") if data.direction == "purchase" else (data.customer, "customer")
    cp = _sub(el, "Counterparty", role=role)
    _sub(cp, "Name", _txt(party.name, 255) or "Неизвестен")
    if party.eik:
        _sub(cp, "EIK", party.eik)
    if re.fullmatch(r"[A-Z]{2}[0-9A-Z]{2,13}", party.vat_number or ""):
        _sub(cp, "VATNumber", party.vat_number)
    if party.country:
        _sub(cp, "Country", _txt(party.country, 255))

    lines = _sub(el, "Lines")
    for i, ln in enumerate(data.lines, start=1):
        le = _sub(lines, "Line", no=i)
        _sub(le, "Description", _txt(ln.description, 500))
        if ln.quantity:
            _sub(le, "Quantity", _decimal(ln.quantity))
        if ln.unit:
            _sub(le, "Unit", _txt(ln.unit, 255))
        if ln.unit_price:
            _sub(le, "UnitPrice", _decimal(ln.unit_price))
        _sub(le, "NetAmount", _amount(ln.net_amount))
        _sub(le, "VATRate", _amount(ln.vat_rate))
        _sub(le, "VATAmount", _amount(ln.vat_amount))
        _sub(le, "AccountCode", ln.account_code)

    t = _sub(el, "Totals")
    _sub(t, "NetAmount", _amount(data.totals.net_amount))
    _sub(t, "VATAmount", _amount(data.totals.vat_amount))
    _sub(t, "GrossAmount", _amount(data.totals.gross_amount))

    je = _sub(el, "JournalEntries")
    for i, e in enumerate(doc.journal or [], start=1):
        ee = _sub(je, "Entry", no=i)
        _sub(ee, "Debit", e["debit"])
        _sub(ee, "Credit", e["credit"])
        _sub(ee, "Amount", _amount(e["amount"]))
        if e.get("description"):
            _sub(ee, "Description", _txt(e["description"], 500))

    _sub(el, "Source", fileName=_txt(doc.original_filename, 500), sha256=doc.sha256)


def build_export(company: Company, documents: list[Document],
                 period_from: str | None = None, period_to: str | None = None) -> bytes:
    for doc in documents:
        if not doc.extracted or not doc.journal:
            raise ExportError(f"Документ #{doc.id} няма счетоводни статии и не може да се експортира.")

    root = etree.Element(f"{{{NS}}}AccountingExport", nsmap={None: NS}, schemaVersion="1.0")

    header = _sub(root, "Header")
    _sub(header, "GeneratedAt", datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    _sub(header, "Software", SOFTWARE)
    _sub(header, "BookCurrency", settings.book_currency)
    comp = _sub(header, "Company")
    _sub(comp, "Name", _txt(company.name, 255))
    _sub(comp, "EIK", company.eik)
    if company.vat_number:
        _sub(comp, "VATNumber", company.vat_number)
    if period_from or period_to:
        period = _sub(header, "Period")
        if period_from:
            _sub(period, "From", period_from)
        if period_to:
            _sub(period, "To", period_to)

    # Обороти и използвани сметки
    debit, credit = defaultdict(Decimal), defaultdict(Decimal)
    used: set[str] = set()
    summary = {"purchase": [Decimal(0), Decimal(0)], "sale": [Decimal(0), Decimal(0)]}
    for doc in documents:
        for e in doc.journal:
            debit[e["debit"]] += d(e["amount"])
            credit[e["credit"]] += d(e["amount"])
            used.update((e["debit"], e["credit"]))
        data = doc.extracted
        used.update(ln["account_code"] for ln in data["lines"])
        rate = d(data.get("exchange_rate") or 1)
        bucket = summary[data["direction"]]
        bucket[0] += q2(d(data["totals"]["net_amount"]) * rate)
        bucket[1] += q2(d(data["totals"]["vat_amount"]) * rate)

    chart = _sub(root, "ChartOfAccounts")
    for code in sorted(used):
        acc = coa.get(code)
        if acc is None:
            raise ExportError(f"Сметка {code} не съществува в сметкоплана.")
        _sub(chart, "Account", code=acc.code, name=acc.name, category=acc.category)

    docs_el = _sub(root, "Documents")
    for doc in documents:
        _add_document(docs_el, doc)

    turnovers = _sub(root, "AccountTurnovers")
    for code in sorted(set(debit) | set(credit)):
        acc_el = _sub(turnovers, "Account", code=code)
        _sub(acc_el, "DebitTurnover", _amount(debit[code]))
        _sub(acc_el, "CreditTurnover", _amount(credit[code]))

    s = _sub(root, "Summary")
    _sub(s, "DocumentCount", len(documents))
    _sub(s, "PurchasesNet", _amount(summary["purchase"][0]))
    _sub(s, "PurchasesVAT", _amount(summary["purchase"][1]))
    _sub(s, "SalesNet", _amount(summary["sale"][0]))
    _sub(s, "SalesVAT", _amount(summary["sale"][1]))

    xsd = schema()
    if not xsd.validate(root):
        errors = "; ".join(f"ред {e.line}: {e.message}" for e in list(xsd.error_log)[:5])
        raise ExportError(f"XML не съответства на схемата: {errors}")

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
