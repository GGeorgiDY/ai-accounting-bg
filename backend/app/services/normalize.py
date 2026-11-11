"""Нормализация и проверка на извлечените данни + изграждане на статиите.

Всяко съмнение се записва като предупреждение -> документът отива за преглед
от счетоводител ("needs_review"), вместо тихо да влезе в експорта.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from difflib import SequenceMatcher

from app import chart_of_accounts as coa
from app.config import settings
from app.models import Company
from app.schemas import DIRECTIONS, DOC_TYPES, PAYMENT_METHODS, POSTABLE_DOC_TYPES, DocumentData, Line
from app.services.accounting import build_journal, d, default_rate, q2

TOLERANCE = Decimal("0.02")
KNOWN_VAT_RATES = {Decimal(0), Decimal(9), Decimal(20)}

CURRENCY_ALIASES = {
    "ЛВ": "BGN", "ЛВ.": "BGN", "ЛЕВА": "BGN", "ЛЕВ": "BGN", "LEV": "BGN", "LV": "BGN", "BGL": "BGN",
    "€": "EUR", "ЕВРО": "EUR", "EURO": "EUR", "$": "USD", "ДОЛАРА": "USD",
}

_SUFFIX_RE = re.compile(r"\b(еоод|оод|еад|ад|ет|сд|кд|ltd|llc|gmbh|eood|ood|ead|ad)\b", re.IGNORECASE)


@dataclass
class Result:
    data: DocumentData
    direction: str
    journal: list[dict]
    warnings: list[str] = field(default_factory=list)


def digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def clean_vat(s: str) -> str:
    v = re.sub(r"[^A-Z0-9]", "", (s or "").upper())
    if v.isdigit() and len(v) in (9, 10, 13):
        v = "BG" + v
    return v


def norm_name(s: str) -> str:
    s = (s or "").lower().replace('"', " ").replace("„", " ").replace("“", " ")
    s = _SUFFIX_RE.sub(" ", s)
    return " ".join(re.sub(r"[^\w]", " ", s).split())


def parse_date(s: str) -> str:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def detect_direction(company: Company, data: DocumentData) -> tuple[str, str]:
    """Връща (посока, източник). Приоритет: ЕИК/ДДС № > име > предложение на модела."""
    ours = {digits(company.eik), digits(company.vat_number)} - {""}
    sup = {digits(data.supplier.eik), digits(data.supplier.vat_number)} - {""}
    cus = {digits(data.customer.eik), digits(data.customer.vat_number)} - {""}
    in_sup, in_cus = bool(ours & sup), bool(ours & cus)
    if in_sup and not in_cus:
        return "sale", "id"
    if in_cus and not in_sup:
        return "purchase", "id"

    ours_name = norm_name(company.name)
    sr = SequenceMatcher(None, ours_name, norm_name(data.supplier.name)).ratio()
    cr = SequenceMatcher(None, ours_name, norm_name(data.customer.name)).ratio()
    if max(sr, cr) >= 0.85 and abs(sr - cr) >= 0.15:
        return ("sale" if sr > cr else "purchase"), "name"

    if data.direction in ("purchase", "sale"):
        return data.direction, "llm"
    return "unknown", "none"


def _normalize_fields(data: DocumentData, w: list[str]) -> None:
    if data.document_type not in DOC_TYPES:
        data.document_type = "other"
    if data.payment_method not in PAYMENT_METHODS:
        data.payment_method = "unknown"

    cur = (data.currency or "").strip().upper()
    cur = CURRENCY_ALIASES.get(cur, cur)
    if not re.fullmatch(r"[A-Z]{3}", cur):
        w.append(f"Валутата не е разпозната ('{data.currency}') — приета е {settings.book_currency}.")
        cur = settings.book_currency
    data.currency = cur

    for attr in ("issue_date", "tax_event_date", "due_date"):
        raw = getattr(data, attr)
        parsed = parse_date(raw)
        if raw and not parsed:
            w.append(f"Невалидна дата в поле {attr}: '{raw}'.")
        setattr(data, attr, parsed)
    if not data.issue_date:
        w.append("Липсва дата на издаване.")
    if not data.document_number:
        w.append("Липсва номер на документа.")

    for party in (data.supplier, data.customer):
        party.eik = digits(party.eik)
        party.vat_number = clean_vat(party.vat_number)
        party.country = (party.country or "").strip()
        if party.eik and len(party.eik) not in (9, 13):
            party.eik = ""


def _close(a, b) -> bool:
    return abs(d(a) - d(b)) <= TOLERANCE


def _note(data: DocumentData, text: str) -> None:
    data.notes = f"{data.notes} | {text}".strip(" |") if data.notes else text


def _autocorrect(data: DocumentData) -> None:
    """Поправя типични грешки на малките модели, само когато резултатът е еднозначно консистентен.
    Всяка корекция се записва в notes (суровият отговор на модела остава в llm_raw за одит)."""
    # 1) Ред, който е сбор на всички останали (моделът е добавил "междинна сума" като ред)
    if len(data.lines) >= 3:
        for i, ln in enumerate(data.lines):
            others = [o for j, o in enumerate(data.lines) if j != i]
            if _close(ln.net_amount, sum(d(o.net_amount) for o in others)) and \
                    _close(ln.vat_amount, sum(d(o.vat_amount) for o in others)):
                data.lines.pop(i)
                _note(data, f"Автокорекция: премахнат ред-сбор „{ln.description[:40]}“")
                break

    # 2) Тотали, които не съвпадат, но редовете са вътрешно консистентни
    if not data.lines:
        return
    lines_net = sum((d(ln.net_amount) for ln in data.lines), Decimal(0))
    lines_vat = sum((d(ln.vat_amount) for ln in data.lines), Decimal(0))
    t = data.totals
    totals_ok = _close(t.net_amount, lines_net) and _close(t.vat_amount, lines_vat) and \
        _close(d(t.net_amount) + d(t.vat_amount), t.gross_amount)
    lines_ok = all(
        _close(q2(d(ln.net_amount) * d(ln.vat_rate) / 100), ln.vat_amount) for ln in data.lines
    )
    gross = lines_net + lines_vat
    # редовете се потвърждават от поне една сума от документа (основа, ДДС или общо)
    confirmed = any(_close(x, y) for x, y in (
        (t.net_amount, lines_net), (t.vat_amount, lines_vat), (t.gross_amount, gross), (t.net_amount, gross)))
    if not totals_ok and lines_ok and confirmed:
        old = (t.net_amount, t.vat_amount, t.gross_amount)
        t.net_amount, t.vat_amount, t.gross_amount = float(q2(lines_net)), float(q2(lines_vat)), float(q2(gross))
        _note(data, f"Автокорекция: тоталите преизчислени от редовете (бяха {old[0]}/{old[1]}/{old[2]})")


def _normalize_amounts(data: DocumentData, w: list[str], autocorrect: bool) -> None:
    # Кредитно известие -> отрицателни суми (сторно). Идемпотентно.
    if data.document_type == "credit_note":
        for ln in data.lines:
            ln.net_amount, ln.vat_amount = -abs(ln.net_amount), -abs(ln.vat_amount)
        t = data.totals
        t.net_amount, t.vat_amount, t.gross_amount = -abs(t.net_amount), -abs(t.vat_amount), -abs(t.gross_amount)

    data.lines = [ln for ln in data.lines if ln.net_amount or ln.vat_amount or ln.description]

    for ln in data.lines:
        if not ln.vat_amount and ln.vat_rate:
            ln.vat_amount = float(q2(d(ln.net_amount) * d(ln.vat_rate) / 100))

    if autocorrect:
        _autocorrect(data)

    t = data.totals
    lines_net = sum((d(ln.net_amount) for ln in data.lines), Decimal(0))
    lines_vat = sum((d(ln.vat_amount) for ln in data.lines), Decimal(0))
    if not t.net_amount and data.lines:
        t.net_amount = float(q2(lines_net))
    if not t.vat_amount and lines_vat:
        t.vat_amount = float(q2(lines_vat))
    if not t.gross_amount:
        t.gross_amount = float(q2(d(t.net_amount) + d(t.vat_amount)))

    if not data.lines and t.net_amount:
        data.lines = [Line(description="Обобщен ред (редовете не са разпознати)",
                           quantity=1, unit_price=t.net_amount, net_amount=t.net_amount,
                           vat_rate=0, vat_amount=t.vat_amount)]
        w.append("Не са разпознати отделни редове — създаден е обобщен ред.")
    if not data.lines:
        w.append("Не са открити суми в документа.")
        return

    if abs(lines_net - d(t.net_amount)) > TOLERANCE and lines_net:
        w.append(f"Сумата по редове ({q2(lines_net)}) не съвпада с данъчната основа ({q2(t.net_amount)}).")
    if abs(d(t.net_amount) + d(t.vat_amount) - d(t.gross_amount)) > TOLERANCE:
        w.append(f"Основа + ДДС ({q2(d(t.net_amount) + d(t.vat_amount))}) ≠ общо ({q2(t.gross_amount)}).")
    if lines_vat and abs(lines_vat - d(t.vat_amount)) > TOLERANCE:
        w.append(f"ДДС по редове ({q2(lines_vat)}) не съвпада с общия ДДС ({q2(t.vat_amount)}).")
    for i, ln in enumerate(data.lines, start=1):
        if d(ln.vat_rate) not in KNOWN_VAT_RATES:
            w.append(f"Ред {i}: необичайна ДДС ставка {ln.vat_rate}%.")
        elif abs(q2(d(ln.net_amount) * d(ln.vat_rate) / 100) - d(ln.vat_amount)) > Decimal("0.05"):
            w.append(f"Ред {i}: ДДС {ln.vat_amount} не отговаря на {ln.vat_rate}% от {ln.net_amount}.")


def _validate_accounts(company: Company, data: DocumentData, direction: str, w: list[str]) -> None:
    valid = {a.code for a in coa.line_accounts(direction)}
    profile = set(company.allowed_accounts or [])
    fallback = coa.FALLBACK_PURCHASE if direction == "purchase" else coa.FALLBACK_SALE
    kind = "покупка" if direction == "purchase" else "продажба"
    for i, ln in enumerate(data.lines, start=1):
        code = (ln.account_code or "").strip()
        if code not in valid:
            w.append(f"Ред {i}: сметка '{code or '-'}' е неподходяща за {kind} — заменена с {fallback}.")
            code = fallback
        elif profile and code not in profile and code != fallback:
            w.append(f"Ред {i}: сметка {code} е извън профила на фирмата.")
        if code == fallback:
            w.append(f"Ред {i}: използвана е резервна сметка {fallback} — проверете контировката.")
        ln.account_code = code


def finalize(company: Company, data: DocumentData, *, from_llm: bool) -> Result:
    """from_llm=True: данни директно от модела; False: редактирани от счетоводител."""
    w: list[str] = []
    _normalize_fields(data, w)

    if from_llm:
        direction, source = detect_direction(company, data)
        if source == "llm":
            w.append("ЕИК/ДДС № на фирмата не е открит в документа — посоката е предложена от AI.")
        elif source == "none":
            w.append("Не може да се определи дали документът е покупка или продажба.")
        if data.confidence and data.confidence < 0.6:
            w.append(f"Ниска увереност на модела ({data.confidence:.2f}).")
    else:
        direction = data.direction if data.direction in DIRECTIONS else "unknown"
        if direction == "unknown":
            w.append("Изберете дали документът е покупка или продажба.")
    data.direction = direction

    _normalize_amounts(data, w, autocorrect=from_llm)

    journal: list[dict] = []
    if data.document_type not in POSTABLE_DOC_TYPES:
        w.append(f"Документ от вид '{data.document_type}' не се осчетоводява (напр. проформа).")
    elif direction in ("purchase", "sale") and data.lines:
        _validate_accounts(company, data, direction, w)
        rate = default_rate(data.currency, settings.book_currency)
        if rate is None and data.exchange_rate:
            rate = d(data.exchange_rate)
        if rate is None:
            w.append(f"Документът е в {data.currency} — въведете курс към {settings.book_currency}.")
        else:
            data.exchange_rate = float(rate)
            journal = build_journal(data, direction, rate)

    # премахване на дублирани предупреждения, запазвайки реда
    return Result(data=data, direction=direction, journal=journal, warnings=list(dict.fromkeys(w)))
