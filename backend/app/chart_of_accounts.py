"""Сметкоплан (v1).

Базиран на Националния сметкоплан (раздели 1-7), разширен с аналитични
подсметки (4 цифри), удобни за автоматично контиране от фактури.

usage:
  purchase - може да се избере за ред от входяща фактура (разход/актив)
  sale     - може да се избере за ред от изходяща фактура (приход)
  system   - използва се само от правилата за контиране (401, 411, 4531...)
  group    - синтетична/групова сметка, не се контира директно
"""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    category: str  # asset | liability | equity | expense | revenue
    usage: str     # purchase | sale | system | group

    @property
    def postable(self) -> bool:
        return self.usage != "group"

    def to_dict(self) -> dict:
        return asdict(self) | {"postable": self.postable}


_A = Account

CHART: list[Account] = [
    # Раздел 1 — Капитали
    _A("101", "Основен капитал", "equity", "system"),
    _A("122", "Неразпределена печалба", "equity", "system"),
    _A("123", "Печалби и загуби от текущата година", "equity", "system"),
    # Раздел 2 — Дълготрайни активи
    _A("203", "Машини, оборудване и компютърна техника", "asset", "purchase"),
    _A("205", "Транспортни средства", "asset", "purchase"),
    _A("206", "Стопански инвентар (ДМА)", "asset", "purchase"),
    _A("213", "Програмни продукти (НДА)", "asset", "purchase"),
    # Раздел 3 — Материални запаси
    _A("302", "Материали", "asset", "purchase"),
    _A("304", "Стоки", "asset", "purchase"),
    # Раздел 4 — Разчети
    _A("401", "Доставчици", "liability", "system"),
    _A("411", "Клиенти", "asset", "system"),
    _A("453", "Разчети за данък върху добавената стойност", "liability", "group"),
    _A("4531", "Начислен ДДС за покупките", "asset", "system"),
    _A("4532", "Начислен ДДС за продажбите", "liability", "system"),
    # Раздел 5 — Финансови средства
    _A("501", "Каса в лева/евро", "asset", "system"),
    _A("503", "Разплащателна сметка", "asset", "system"),
    # Раздел 6 — Разходи
    _A("601", "Разходи за материали", "expense", "group"),
    _A("6011", "Материали за основна дейност", "expense", "purchase"),
    _A("6012", "Горива и смазочни материали", "expense", "purchase"),
    _A("6013", "Електрическа енергия", "expense", "purchase"),
    _A("6014", "Вода", "expense", "purchase"),
    _A("6015", "Канцеларски материали и консумативи", "expense", "purchase"),
    _A("6016", "Дребен инвентар и резервни части", "expense", "purchase"),
    _A("6017", "Опаковки и амбалаж", "expense", "purchase"),
    _A("602", "Разходи за външни услуги", "expense", "group"),
    _A("6021", "Наеми", "expense", "purchase"),
    _A("6022", "Телекомуникации и интернет", "expense", "purchase"),
    _A("6023", "Счетоводни, правни и консултантски услуги", "expense", "purchase"),
    _A("6024", "Софтуер, лицензи, хостинг и облачни услуги", "expense", "purchase"),
    _A("6025", "Ремонт и поддръжка", "expense", "purchase"),
    _A("6026", "Транспортни и куриерски услуги", "expense", "purchase"),
    _A("6027", "Реклама и маркетинг", "expense", "purchase"),
    _A("6028", "Охрана и СОТ", "expense", "purchase"),
    _A("6029", "Други външни услуги", "expense", "purchase"),
    _A("603", "Разходи за амортизации", "expense", "system"),
    _A("604", "Разходи за заплати", "expense", "system"),
    _A("605", "Разходи за осигуровки", "expense", "system"),
    _A("609", "Други разходи", "expense", "group"),
    _A("6091", "Командировки", "expense", "purchase"),
    _A("6092", "Представителни разходи", "expense", "purchase"),
    _A("6093", "Данъци и такси", "expense", "purchase"),
    _A("6099", "Други разходи", "expense", "purchase"),
    _A("629", "Други финансови разходи (банкови такси)", "expense", "purchase"),
    # Раздел 7 — Приходи
    _A("702", "Приходи от продажби на стоки", "revenue", "group"),
    _A("7021", "Продажби на стоки на едро", "revenue", "sale"),
    _A("7022", "Продажби на стоки на дребно", "revenue", "sale"),
    _A("703", "Приходи от продажби на услуги", "revenue", "group"),
    _A("7031", "Разработка на софтуер", "revenue", "sale"),
    _A("7032", "Абонаментна поддръжка", "revenue", "sale"),
    _A("7033", "Консултантски услуги и обучения", "revenue", "sale"),
    _A("7034", "Транспортни услуги и доставка", "revenue", "sale"),
    _A("7035", "Лицензи и SaaS абонаменти", "revenue", "sale"),
    _A("7039", "Други услуги", "revenue", "sale"),
    _A("704", "Приходи от продажби на материали", "revenue", "sale"),
    _A("709", "Други приходи", "revenue", "sale"),
]

BY_CODE: dict[str, Account] = {a.code: a for a in CHART}

# Сметки, които правилата за контиране използват
SUPPLIERS = "401"
CLIENTS = "411"
VAT_PURCHASES = "4531"
VAT_SALES = "4532"
CASH = "501"

FALLBACK_PURCHASE = "6099"
FALLBACK_SALE = "709"


def get(code: str) -> Account | None:
    return BY_CODE.get(code)


def line_accounts(direction: str | None = None, allowed: list[str] | None = None) -> list[Account]:
    """Сметки, които могат да се изберат за ред от фактура."""
    usages = {"purchase": {"purchase"}, "sale": {"sale"}}.get(direction or "", {"purchase", "sale"})
    result = [a for a in CHART if a.usage in usages]
    if allowed:
        allowed_set = set(allowed)
        restricted = [a for a in result if a.code in allowed_set]
        # Резервните сметки винаги са налични, за да има къде да отиде неясен разход/приход
        for fb in (FALLBACK_PURCHASE, FALLBACK_SALE):
            acc = BY_CODE[fb]
            if acc.usage in usages and acc not in restricted:
                restricted.append(acc)
        result = restricted
    return result
