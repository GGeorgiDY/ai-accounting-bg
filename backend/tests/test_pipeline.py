"""Тестове на детерминистичната част (без БД и без LLM).

docker compose run --rm --no-deps -v ./backend/tests:/app/tests backend python -m pytest -q tests
или без pytest:  python -m tests.test_pipeline
"""
from decimal import Decimal

from lxml import etree

from app.models import Company, Document
from app.schemas import DocumentData
from app.services.normalize import finalize
from app.services.xml_export import NS, build_export

COMPANY = Company(id=1, name="ТехноСофт Солюшънс ООД", eik="204512378", vat_number="BG204512378",
                  allowed_accounts=["6024", "203", "6016", "7031", "7032", "7033"])

PURCHASE = {
    "document_type": "invoice", "document_number": "0000004521", "issue_date": "03.10.2026",
    "supplier": {"name": "Клауд Хост ЕООД", "eik": "205998877", "vat_number": "BG205998877", "country": "BG"},
    "customer": {"name": "ТехноСофт Солюшънс ООД", "eik": "204512378", "vat_number": "BG 204512378", "country": "BG"},
    "direction": "sale",  # нарочно грешно — трябва да се коригира по ЕИК
    "currency": "EUR", "payment_method": "bank",
    "lines": [
        {"description": "VPS", "quantity": 3, "unit": "бр.", "unit_price": 180, "net_amount": 540, "vat_rate": 20, "vat_amount": 108, "account_code": "6024"},
        {"description": "DB", "quantity": 1, "unit": "бр.", "unit_price": 240, "net_amount": "240,00", "vat_rate": 20, "vat_amount": 48, "account_code": "7031"},
    ],
    "totals": {"net_amount": 780, "vat_amount": 156, "gross_amount": 936},
    "confidence": 0.95, "notes": "",
}


def _doc(result, doc_id=1):
    doc = Document(id=doc_id, original_filename="f.pdf", sha256="a" * 64, status="processed")
    doc.extracted = result.data.model_dump()
    doc.journal = result.journal
    return doc


def test_purchase_direction_accounts_and_xml():
    r = finalize(COMPANY, DocumentData.model_validate(PURCHASE), from_llm=True)
    assert r.direction == "purchase"
    assert r.data.issue_date == "2026-10-03"
    # 7031 е приходна сметка -> заменена с резервната 6099
    assert r.data.lines[1].account_code == "6099"
    assert any("6099" in w for w in r.warnings)
    pairs = {(e["debit"], e["credit"]): Decimal(e["amount"]) for e in r.journal}
    assert pairs[("6024", "401")] == Decimal("540.00")
    assert pairs[("4531", "401")] == Decimal("156.00")

    xml = build_export(COMPANY, [_doc(r)])
    root = etree.fromstring(xml)
    assert root.find(f"{{{NS}}}Summary/{{{NS}}}PurchasesVAT").text == "156.00"


def test_bgn_converted_to_eur_and_cash_sale():
    data = dict(PURCHASE, currency="лв.", payment_method="cash",
                supplier=PURCHASE["customer"], customer=PURCHASE["supplier"])
    data["lines"] = [dict(PURCHASE["lines"][0], account_code="7031", net_amount=1955.83, vat_amount=391.17)]
    data["totals"] = {"net_amount": 1955.83, "vat_amount": 391.17, "gross_amount": 2347.0}
    r = finalize(COMPANY, DocumentData.model_validate(data), from_llm=True)
    assert r.direction == "sale" and r.data.currency == "BGN"
    pairs = {(e["debit"], e["credit"]): Decimal(e["amount"]) for e in r.journal}
    assert pairs[("411", "7031")] == Decimal("1000.00")
    assert pairs[("501", "411")] == pairs[("411", "7031")] + pairs[("411", "4532")]
    build_export(COMPANY, [_doc(r)])


def test_credit_note_is_negative():
    data = dict(PURCHASE, document_type="credit_note")
    data["lines"] = [PURCHASE["lines"][0]]
    data["totals"] = {"net_amount": 540, "vat_amount": 108, "gross_amount": 648}
    r = finalize(COMPANY, DocumentData.model_validate(data), from_llm=True)
    assert all(Decimal(e["amount"]) < 0 for e in r.journal)
    build_export(COMPANY, [_doc(r)])


def test_usd_requires_rate():
    data = dict(PURCHASE, currency="USD")
    data["lines"] = [PURCHASE["lines"][0]]
    data["totals"] = {"net_amount": 540, "vat_amount": 108, "gross_amount": 648}
    r = finalize(COMPANY, DocumentData.model_validate(data), from_llm=True)
    assert r.journal == [] and any("курс" in w for w in r.warnings)
    data["exchange_rate"] = 0.9
    r = finalize(COMPANY, DocumentData.model_validate(r.data.model_dump() | {"exchange_rate": 0.9}), from_llm=False)
    assert r.journal and r.journal[0]["amount"] == "486.00"


def test_autocorrect_subtotal_row_and_gross_as_net():
    """Реален отговор на qwen2.5:7b: добавен ред-сбор + сумата за плащане записана като основа."""
    data = dict(PURCHASE)
    data["lines"] = [
        dict(PURCHASE["lines"][0], net_amount=540, vat_amount=108),
        dict(PURCHASE["lines"][0], net_amount=240, vat_amount=48),
        dict(PURCHASE["lines"][0], net_amount=35, vat_amount=7),
        dict(PURCHASE["lines"][0], description="", net_amount=815, vat_amount=163),
    ]
    data["totals"] = {"net_amount": 978, "vat_amount": 163, "gross_amount": 1141}
    r = finalize(COMPANY, DocumentData.model_validate(data), from_llm=True)
    assert len(r.data.lines) == 3
    assert (r.data.totals.net_amount, r.data.totals.vat_amount, r.data.totals.gross_amount) == (815, 163, 978)
    assert r.warnings == [], r.warnings
    assert "Автокорекция" in r.data.notes


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
