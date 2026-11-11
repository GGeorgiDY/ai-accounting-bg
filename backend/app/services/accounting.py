"""Правила за контиране (детерминистични).

Покупка:   Дт <сметка на реда>  Кт 401   (данъчна основа)
           Дт 4531              Кт 401   (ДДС)
           Дт 401               Кт 501   (само при плащане в брой)
Продажба:  Дт 411  Кт <сметка на реда>   (данъчна основа)
           Дт 411  Кт 4532               (ДДС)
           Дт 501  Кт 411                (само при плащане в брой)
Кредитно известие: същите статии с отрицателни суми (червено сторно).
Сумите в статиите са във валутата на счетоводството (BOOK_CURRENCY).
"""
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from app import chart_of_accounts as coa
from app.schemas import DocumentData

CENT = Decimal("0.01")
BGN_PER_EUR = Decimal("1.95583")  # фиксиран курс


def d(x) -> Decimal:
    return Decimal(str(x or 0))


def q2(x) -> Decimal:
    return d(x).quantize(CENT, rounding=ROUND_HALF_UP)


def default_rate(currency: str, book_currency: str) -> Decimal | None:
    """Колко единици счетоводна валута струва 1 единица валута на документа."""
    if currency == book_currency:
        return Decimal(1)
    if currency == "BGN" and book_currency == "EUR":
        return (Decimal(1) / BGN_PER_EUR).quantize(Decimal("0.0000000001"))
    if currency == "EUR" and book_currency == "BGN":
        return BGN_PER_EUR
    return None


def _entry(debit: str, credit: str, amount: Decimal, description: str) -> dict:
    return {"debit": debit, "credit": credit, "amount": str(q2(amount)), "description": description[:250]}


def build_journal(data: DocumentData, direction: str, rate: Decimal) -> list[dict]:
    per_account: dict[str, Decimal] = defaultdict(Decimal)
    for line in data.lines:
        per_account[line.account_code] += d(line.net_amount)

    conv = lambda amount: q2(d(amount) * rate)  # noqa: E731
    number = data.document_number or "б/н"
    entries: list[dict] = []

    if direction == "purchase":
        who = data.supplier.name or "доставчик"
        for acc, net in per_account.items():
            entries.append(_entry(acc, coa.SUPPLIERS, conv(net), f"{who}, док. {number}: {coa.BY_CODE[acc].name}"))
        vat = conv(data.totals.vat_amount)
        if vat:
            entries.append(_entry(coa.VAT_PURCHASES, coa.SUPPLIERS, vat, f"ДДС по док. {number}"))
        if data.payment_method == "cash":
            total = sum((d(e["amount"]) for e in entries), Decimal(0))
            entries.append(_entry(coa.SUPPLIERS, coa.CASH, total, f"Плащане в брой по док. {number}"))
    elif direction == "sale":
        who = data.customer.name or "клиент"
        for acc, net in per_account.items():
            entries.append(_entry(coa.CLIENTS, acc, conv(net), f"{who}, док. {number}: {coa.BY_CODE[acc].name}"))
        vat = conv(data.totals.vat_amount)
        if vat:
            entries.append(_entry(coa.CLIENTS, coa.VAT_SALES, vat, f"ДДС по док. {number}"))
        if data.payment_method == "cash":
            total = sum((d(e["amount"]) for e in entries), Decimal(0))
            entries.append(_entry(coa.CASH, coa.CLIENTS, total, f"Получено в брой по док. {number}"))
    else:
        raise ValueError(f"Unsupported direction: {direction}")

    return [e for e in entries if d(e["amount"]) != 0]
