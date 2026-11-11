    """Изграждане на промпта и JSON схемата за извличане на данни от фактура.

Моделът НЕ генерира XML и НЕ решава счетоводните статии. Той само:
  1) извлича реквизитите на документа,
  2) предлага сметка за всеки ред (ограничена чрез enum до позволените сметки).
Всичко останало е детерминистичен код (normalize.py, accounting.py, xml_export.py).
"""
from app import chart_of_accounts as coa
from app.config import settings
from app.models import Company
from app.schemas import DOC_TYPES, PAYMENT_METHODS

SYSTEM_TEMPLATE = """\
Ти си асистент на счетоводна кантора в България. Получаваш текста на първичен счетоводен \
документ (фактура, кредитно или дебитно известие), извлечен от PDF (възможно е с OCR грешки). \
Задачата ти е да извлечеш данните му и да предложиш счетоводна сметка за всеки ред.

ОБЩИ ПРАВИЛА
1. Връщай САМО JSON по зададената схема. Не измисляй данни: ако нещо липсва в документа, \
върни "" за текст и 0 за число.
2. Датите са във формат YYYY-MM-DD (напр. 15.10.2026 -> 2026-10-15).
3. Сумите са числа с точка за десетичен знак, без валута и без разделители за хилядни.
4. ЕИК е 9 или 13 цифри. ДДС номерът е с префикс на държавата (напр. BG123456789).
5. "supplier" е доставчикът/издателят на документа, "customer" е получателят.
6. От 01.01.2026 г. валутата в България е евро (EUR). Ако документът е в лева, върни "BGN". \
Използвай ISO код (EUR, BGN, USD...).
7. За всеки ред: net_amount = сумата БЕЗ ДДС, vat_rate = ставка в % (20, 9 или 0), \
vat_amount = ДДС за реда. Ако ДДС е посочен само общо, разпредели го пропорционално.
8. "lines" съдържа САМО редовете със стоки/услуги от таблицата. НЕ добавяй ред за междинна \
сума, данъчна основа, ДДС или сума за плащане. Не пропускай редове. Ако има отстъпка, \
отрази я като намаление в съответните редове.
8a. totals.net_amount = "Данъчна основа" (без ДДС); totals.vat_amount = "Начислен ДДС"; \
totals.gross_amount = "Сума за плащане" (с ДДС).
9. document_type: "invoice" (фактура), "credit_note" (кредитно известие), "debit_note" \
(дебитно известие), "proforma" (проформа), "other". При кредитно известие сумите са положителни.
10. payment_method: "bank" (банков път), "cash" (в брой), "card" (карта), "other", "unknown".
11. direction: "purchase" ако нашата фирма е получател, "sale" ако нашата фирма е доставчик.
12. account_code: избери САМО от списъка с позволени сметки. При покупка — сметка за разход \
или актив; при продажба — сметка за приход. Следвай указанията в профила на фирмата.
13. confidence: увереност от 0 до 1 в коректността на извлечените данни.
14. notes: кратки бележки на български (напр. "обратно начисляване", "нечетлив ЕИК").

НАШАТА ФИРМА (клиент на кантората)
Име: {name}
ЕИК: {eik}
ДДС №: {vat}
Дейност: {activity}

ПРОФИЛ НА ФИРМАТА (указания от счетоводителя)
{profile}

ПОЗВОЛЕНИ СМЕТКИ ЗА РЕДОВЕТЕ
{accounts}
"""

USER_TEMPLATE = """\
Извлечи данните от следния документ. Файл: {filename}

<<<ДОКУМЕНТ
{text}
ДОКУМЕНТ>>>"""


def allowed_line_accounts(company: Company) -> list[coa.Account]:
    return coa.line_accounts(None, company.allowed_accounts or None)


def build_system_prompt(company: Company) -> str:
    accounts = "\n".join(
        f"- {a.code} {a.name} ({'покупка' if a.usage == 'purchase' else 'продажба'})"
        for a in allowed_line_accounts(company)
    )
    return SYSTEM_TEMPLATE.format(
        name=company.name,
        eik=company.eik,
        vat=company.vat_number or "няма (нерегистрирана по ДДС)",
        activity=company.activity or "-",
        profile=(company.ai_prompt or "Няма допълнителни указания.").strip(),
        accounts=accounts,
    )


def build_user_prompt(filename: str, text: str) -> str:
    return USER_TEMPLATE.format(filename=filename, text=text)


def _party_schema() -> dict:
    props = {k: {"type": "string"} for k in ("name", "eik", "vat_number", "country")}
    return {"type": "object", "properties": props, "required": list(props)}


def build_schema(company: Company) -> dict:
    codes = [a.code for a in allowed_line_accounts(company)]
    line = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "quantity": {"type": "number"},
            "unit": {"type": "string"},
            "unit_price": {"type": "number"},
            "net_amount": {"type": "number"},
            "vat_rate": {"type": "number"},
            "vat_amount": {"type": "number"},
            "account_code": {"type": "string", "enum": codes},
        },
        "required": [
            "description", "quantity", "unit", "unit_price",
            "net_amount", "vat_rate", "vat_amount", "account_code",
        ],
    }
    # Редът на полетата е умишлен: първо страните и посоката, после редовете със сметките.
    props = {
        "document_type": {"type": "string", "enum": list(DOC_TYPES)},
        "document_number": {"type": "string"},
        "issue_date": {"type": "string"},
        "tax_event_date": {"type": "string"},
        "due_date": {"type": "string"},
        "supplier": _party_schema(),
        "customer": _party_schema(),
        "direction": {"type": "string", "enum": ["purchase", "sale"]},
        "currency": {"type": "string"},
        "payment_method": {"type": "string", "enum": list(PAYMENT_METHODS)},
        "lines": {"type": "array", "items": line},
        "totals": {
            "type": "object",
            "properties": {
                "net_amount": {"type": "number"},
                "vat_amount": {"type": "number"},
                "gross_amount": {"type": "number"},
            },
            "required": ["net_amount", "vat_amount", "gross_amount"],
        },
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
    }
    return {"type": "object", "properties": props, "required": list(props)}


DEFAULT_PROMPT_TEMPLATE = f"""\
# Профил на фирмата

## Дейност
<Кратко описание: с какво се занимава фирмата, брой служители, регистрация по ДДС, клиенти.>

## Входящи документи (покупки) — фирмата е ПОЛУЧАТЕЛ
- <Типичен доставчик / предмет> -> <сметка>
- ...

## Изходящи документи (продажби) — фирмата е ДОСТАВЧИК
- <Типична продажба> -> <сметка>
- ...

## Специфики и правила
- Валута по подразбиране: {settings.book_currency}
- <Праг на същественост за ДМА, обратно начисляване, особени доставчици и т.н.>
"""
