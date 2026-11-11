"""Генерира примерни PDF фактури за двете демо компании.

docker compose run --rm worker python -m app.tools.make_samples /samples
"""
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))

TECHNO = ("ТехноСофт Солюшънс ООД", "204512378", "BG204512378", "гр. София, бул. „Цариградско шосе“ 115")
STROY = ("Строймаркет Варна ЕООД", "103874512", "BG103874512", "гр. Варна, ул. „Девня“ 22")


@dataclass
class Invoice:
    filename: str
    title: str
    number: str
    date: str
    supplier: tuple
    customer: tuple
    lines: list  # (описание, к-во, мярка, ед. цена, ДДС %)
    payment: str = "По банков път"
    currency: str = "EUR"
    notes: list = field(default_factory=list)


def q(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


SAMPLES = [
    Invoice("technosoft_purchase_hosting.pdf", "ФАКТУРА", "0000004521", "03.10.2026",
            ("Клауд Хост ЕООД", "205998877", "BG205998877", "гр. София, ул. „Тракия“ 12"), TECHNO,
            [("Облачен сървър VPS-XL, м. октомври 2026", 3, "бр.", "180.00", 20),
             ("Управлявана база данни PostgreSQL", 1, "бр.", "240.00", 20),
             ("Резервни копия (backup) 500 GB", 1, "бр.", "35.00", 20)]),
    Invoice("technosoft_purchase_laptops.pdf", "ФАКТУРА", "2000118734", "14.10.2026",
            ("Компютри Директ АД", "131456789", "BG131456789", "гр. София, бул. „България“ 51"), TECHNO,
            [("Лаптоп Lenovo ThinkPad T14 Gen 6, 32GB RAM, 1TB SSD", 2, "бр.", "1450.00", 20),
             ("Докинг станция USB-C", 2, "бр.", "189.00", 20),
             ("Безжична мишка Logitech MX Master", 2, "бр.", "89.00", 20)]),
    Invoice("technosoft_sale_development.pdf", "ФАКТУРА", "0000000387", "31.10.2026",
            TECHNO, ("Ритейл Плюс АД", "175123456", "BG175123456", "гр. Пловдив, бул. „Марица“ 7"),
            [("Разработка на мобилно приложение за лоялна програма — етап 2 по договор № 14/2026", 1, "бр.", "12500.00", 20),
             ("Абонаментна поддръжка SLA Gold, м. октомври 2026", 1, "мес.", "1800.00", 20),
             ("Обучение на потребители (8 часа)", 8, "ч.", "75.00", 20)]),
    Invoice("stroymarket_purchase_goods.pdf", "ФАКТУРА", "0000072215", "07.10.2026",
            ("Керамика Комерс ООД", "200345678", "BG200345678", "гр. Шумен, Индустриална зона"), STROY,
            [("Тухли керамични 25/38/19 (палет 60 бр.)", 20, "палет", "96.00", 20),
             ("Цимент CEM II 42.5 R, 25 кг", 400, "чувал", "6.20", 20),
             ("Гипсокартон стандартен 12.5 мм", 150, "бр.", "5.40", 20),
             ("Транспорт Шумен - Варна, камион 20 т", 1, "курс", "320.00", 20)]),
    Invoice("stroymarket_purchase_electricity.pdf", "ФАКТУРА", "4400918822", "05.11.2026",
            ("Енерджи Сейлс АД", "103533691", "BG103533691", "гр. Варна, бул. „Владислав Варненчик“ 258"), STROY,
            [("Активна електрическа енергия, м. октомври 2026, ИТН 32Z1400000123456", 8420, "kWh", "0.112", 20),
             ("Мрежови услуги и такса достъп", 1, "бр.", "212.40", 20),
             ("Задължение към обществото", 8420, "kWh", "0.0085", 20)]),
    Invoice("stroymarket_sale_wholesale.pdf", "ФАКТУРА", "0000015032", "21.10.2026",
            STROY, ("Домострой Билд ЕООД", "206112233", "BG206112233", "гр. Варна, ж.к. „Младост“ 140"),
            [("Цимент CEM II 42.5 R, 25 кг", 120, "чувал", "8.90", 20),
             ("Тухли керамични 25/38/19 (палет 60 бр.)", 6, "палет", "138.00", 20),
             ("Лепило за плочки C2TE, 25 кг", 40, "чувал", "14.50", 20),
             ("Доставка до обект с кран, гр. Варна", 1, "курс", "85.00", 20)],
            payment="В брой"),
    Invoice("stroymarket_credit_note.pdf", "КРЕДИТНО ИЗВЕСТИЕ", "0000015047", "24.10.2026",
            STROY, ("Домострой Билд ЕООД", "206112233", "BG206112233", "гр. Варна, ж.к. „Младост“ 140"),
            [("Върнат цимент CEM II 42.5 R, 25 кг (повредени чували)", 10, "чувал", "8.90", 20)],
            notes=["Към фактура № 0000015032 от 21.10.2026 г.", "Основание: върната стока"]),
]


def render(inv: Invoice, out_dir: Path) -> Path:
    path = out_dir / inv.filename
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)
    normal = ParagraphStyle("n", fontName="DejaVu", fontSize=9, leading=12)
    bold = ParagraphStyle("b", parent=normal, fontName="DejaVu-Bold")
    title = ParagraphStyle("t", parent=bold, fontSize=18, leading=22, alignment=1)

    def party(label, p):
        return Paragraph(f"<b>{label}</b><br/>{p[0]}<br/>ЕИК: {p[1]}<br/>ДДС №: {p[2]}<br/>Адрес: {p[3]}", normal)

    story = [
        Paragraph(inv.title, title),
        Paragraph(f"№ {inv.number} / Дата на издаване: {inv.date} / Дата на данъчно събитие: {inv.date}", normal),
        Paragraph("ОРИГИНАЛ", bold),
        Spacer(1, 6 * mm),
        Table([[party("Доставчик:", inv.supplier), party("Получател:", inv.customer)]], colWidths=[90 * mm, 90 * mm]),
        Spacer(1, 6 * mm),
    ]

    rows = [["№", "Описание", "К-во", "Мярка", "Ед. цена", "ДДС %", "Стойност"]]
    net = Decimal(0)
    vat = Decimal(0)
    for i, (desc, qty, unit, price, rate) in enumerate(inv.lines, start=1):
        value = q(Decimal(str(qty)) * Decimal(price))
        net += value
        vat += q(value * rate / 100)
        rows.append([str(i), Paragraph(desc, normal), str(qty), unit, price, f"{rate}%", f"{value:,.2f}".replace(",", " ")])
    t = Table(rows, colWidths=[8 * mm, 80 * mm, 16 * mm, 16 * mm, 20 * mm, 14 * mm, 26 * mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "DejaVu", 8.5),
        ("FONT", (0, 0), (-1, 0), "DejaVu-Bold", 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf3")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ]))
    story += [t, Spacer(1, 4 * mm)]

    fmt = lambda x: f"{x:,.2f} {inv.currency}".replace(",", " ")  # noqa: E731
    totals = Table([
        ["Данъчна основа 20%:", fmt(net)],
        ["Начислен ДДС 20%:", fmt(vat)],
        ["Сума за плащане:", fmt(net + vat)],
    ], colWidths=[50 * mm, 40 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "DejaVu", 9),
        ("FONT", (0, 2), (-1, 2), "DejaVu-Bold", 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, 2), (-1, 2), 0.6, colors.black),
    ]))
    story += [totals, Spacer(1, 6 * mm),
              Paragraph(f"Начин на плащане: {inv.payment}", normal),
              Paragraph("IBAN: BG80 BNBG 9661 1020 3456 78, BIC: BNBGBGSD", normal)]
    story += [Paragraph(n, normal) for n in inv.notes]
    story += [Spacer(1, 10 * mm), Paragraph("Съставил: ................................ Получил: ................................", normal)]
    doc.build(story)
    return path


def main() -> None:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/samples")
    out_dir.mkdir(parents=True, exist_ok=True)
    for inv in SAMPLES:
        print("created", render(inv, out_dir))


if __name__ == "__main__":
    main()
