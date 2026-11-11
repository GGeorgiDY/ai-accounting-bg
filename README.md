# AccountantAI — локално AI осчетоводяване на фактури

Уеб приложение за счетоводна кантора. В него се добавят обслужваните фирми, качват се PDF фактури
за всяка от тях, а **локален AI модел** (без облак, данните не напускат машината) ги
разпознава и осчетоводява. Резултатът е **XML по строга XSD схема**, който отразява сметкоплана.

## Стартиране

Изисква Docker Desktop, ~10 GB свободно място и ~8 GB RAM за Docker.

```bash
docker compose up -d --build
```

Отворете **http://localhost:8080**.

При първото стартиране контейнерът `ollama-pull` тегли модела (`qwen2.5:7b`, ~4.7 GB).
Докато това не приключи, горе вдясно пише „Моделът се изтегля…“. Качените документи стоят
в опашката и се обработват автоматично, когато моделът е готов.

```bash
docker compose logs -f ollama-pull worker   # прогрес на тегленето и обработката
docker compose down                          # спиране (данните остават във volumes)
docker compose down -v                       # спиране + изтриване на всички данни
```

**NVIDIA GPU** (многократно по-бързо):
`docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`

**Примерни фактури** (7 PDF файла за двете демо фирми, записват се в `./samples`):
```bash
docker compose run --rm --no-deps worker python -m app.tools.make_samples /samples
```

**Тестове** (без БД и LLM):
```bash
docker compose run --rm --no-deps -v ./backend/tests:/app/tests backend python -m tests.test_pipeline
```

## Архитектура

```
                       ┌───────────────────────── docker compose ─────────────────────────┐
 Браузър  ──:8080──►   │  frontend (nginx + React SPA)                                     │
                       │      │ /api/*                                                     │
                       │      ▼                                                            │
                       │  backend (FastAPI) ──────────► db (postgres:16)  ◄──── worker     │
                       │   • CRUD компании               • companies           (същият     │
                       │   • качване на PDF              • documents = опашка   image)     │
                       │   • корекции/одобрение                                 │          │
                       │   • XML експорт + XSD                                  ▼          │
                       │                                         ollama (ollama/ollama)    │
                       │  volumes: pgdata, uploads, ollama        └─ ollama-pull (1 път)   │
                       └───────────────────────────────────────────────────────────────────┘
```

| Услуга | Образ | Роля |
|---|---|---|
| `frontend` | собствен (node build → `nginx:1.27-alpine`) | UI и reverse proxy към API |
| `backend` | собствен (`python:3.12-slim`) | REST API (`/api/docs` за Swagger) |
| `worker` | същият като backend | Обработва опашката: PDF → текст/OCR → LLM → проверки → статии |
| `db` | `postgres:16-alpine` (Docker Hub) | Данни + опашка от задачи |
| `ollama` | `ollama/ollama` (Docker Hub) | Локален LLM сървър |
| `ollama-pull` | `ollama/ollama` | Еднократно изтегля модела |

**Защо така:**
- **Опашката е в Postgres** (`SELECT … FOR UPDATE SKIP LOCKED`), затова не е нужен Redis/RabbitMQ.
  Мащабиране: `docker compose up -d --scale worker=2`.
- **API и worker са отделни процеси.** Обработката отнема от 30 сек до 3 мин на CPU и не бива
  да блокира UI.
- **LLM е зад тънък адаптер** (`services/llm.py`). Може да се смени с vLLM или llama.cpp,
  или да се ползва друг модел само чрез `LLM_MODEL` в `.env`.
- **Нови услуги от Docker Hub** (например Redis, MinIO за файлове, Grafana) се добавят като
  нов service в същия compose файл, в същата мрежа.

## Как се обработва една фактура

```
PDF ─► pdfplumber (текстов слой) ─► ако няма текст: OCR (tesseract bul+eng)
    ─► LLM (Ollama, temperature 0, JSON Schema structured output)
         • system prompt = общи правила + ПРОФИЛ НА ФИРМАТА + позволени сметки
         • account_code е enum → моделът физически не може да върне несъществуваща сметка
    ─► normalize.py (детерминистично)
         • посока покупка/продажба по ЕИК/ДДС № (не по преценка на модела)
         • дати, валути (лв.→BGN), ЕИК, ДДС номера
         • проверки: Σ редове = основа, основа + ДДС = общо, ДДС = ставка × основа
         • сметка подходяща ли е за посоката (разход при покупка, приход при продажба)
         • кредитно известие → отрицателни суми (червено сторно)
         • BGN → EUR по фиксиран курс 1.95583; друга валута → изисква курс
    ─► accounting.py — счетоводни статии
    ─► XML dry-run срещу XSD
    ─► статус: processed (без забележки) | needs_review (има предупреждения) | failed
```

**Ключов принцип: LLM-ът само извлича данни. Не пише XML и не съставя статии.**
Счетоводните правила са в код, тестваеми и предвидими. Всяко съмнение отива за преглед, а не
директно в експорта. Счетоводителят може да коригира всяко поле в UI. Статиите се
преизчисляват и документът се одобрява.

### Правила за контиране

| Документ | Статии |
|---|---|
| Покупка | Дт `<сметка от реда>` / Кт 401 — основа; Дт 4531 / Кт 401 — ДДС; при плащане в брой Дт 401 / Кт 501 |
| Продажба | Дт 411 / Кт `<сметка от реда>` — основа; Дт 411 / Кт 4532 — ДДС; при плащане в брой Дт 501 / Кт 411 |
| Кредитно известие | Същите статии с отрицателни суми |

## Сметкоплан

`backend/app/chart_of_accounts.py`: Националният сметкоплан (раздели 1–7) с аналитични
подсметки за автоматично контиране. Примери: 6024 „Софтуер, лицензи, хостинг“,
6026 „Транспортни и куриерски услуги“, 7031 „Разработка на софтуер“,
7034 „Транспортни услуги и доставка“. Всяка сметка има категория (asset, liability, equity,
expense, revenue) и предназначение:
- `purchase`: може да се ползва за ред от покупка;
- `sale`: може да се ползва за ред от продажба;
- `system`: ползва се само от правилата за контиране (401, 411, 4531, 4532, 501);
- `group`: синтетична сметка, не се контира.

## XML формат

Схема: `backend/app/xml/accounting_export_v1.xsd`, namespace `urn:bg:accounting:export:v1`.

```xml
<AccountingExport xmlns="urn:bg:accounting:export:v1" schemaVersion="1.0">
  <Header>  GeneratedAt, Software, BookCurrency, Company(Name, EIK, VATNumber), Period </Header>
  <ChartOfAccounts>
    <Account code="401" name="Доставчици" category="liability"/> …
  </ChartOfAccounts>
  <Documents>
    <Document id="12" kind="invoice" direction="purchase" status="approved">
      <Number/> <IssueDate/> <TaxEventDate/> <Currency/> <ExchangeRate/> <PaymentMethod/>
      <Counterparty role="supplier"> Name, EIK, VATNumber, Country </Counterparty>
      <Lines> <Line no="1"> Description, Quantity, Unit, UnitPrice, NetAmount, VATRate, VATAmount, AccountCode </Line> </Lines>
      <Totals> NetAmount, VATAmount, GrossAmount </Totals>
      <JournalEntries> <Entry no="1"> Debit, Credit, Amount, Description </Entry> </JournalEntries>
      <Source fileName="…" sha256="…"/>
    </Document>
  </Documents>
  <AccountTurnovers> <Account code="6024"> DebitTurnover, CreditTurnover </Account> </AccountTurnovers>
  <Summary> DocumentCount, PurchasesNet, PurchasesVAT, SalesNet, SalesVAT </Summary>
</AccountingExport>
```

Схемата гарантира следното:
- всяка сметка в статия, ред или оборот съществува в `ChartOfAccounts` (`xs:keyref`);
- сумите са с точно 2 знака след десетичната точка;
- ЕИК, ДДС номерата, валутите и датите са във валиден формат;
- `id` на документите са уникални.

Експортът е за период и по подразбиране включва само документи със статус `processed`
и `approved`.

## AI профил на фирмата (промпт)

Всяка фирма има профил в свободен текст (Markdown). Той описва дейността ѝ, типичните
доставчици и продажби, към коя сметка отива всеки вид разход или приход, както и
спецификите (праг на същественост за ДМА, обратно начисляване, разделяне на стоки и
транспорт). Профилът се подава на модела при всяка фактура и се редактира от UI-а
(таб „AI профил“). Към профила има и списък с **позволени сметки**, които стават `enum`
в JSON схемата.

Демо фирмите се зареждат при първото стартиране:
- **ТехноСофт Солюшънс ООД**: софтуерна компания (хостинг, лицензи, наем, техника → 203/6016;
  продажби 7031/7032/7033/7035). Профил: `backend/seed/prompts/technosoft.md`.
- **Строймаркет Варна ЕООД**: търговия със строителни материали (стоки → 304, транспорт → 6026,
  горива, ел. енергия; продажби на едро/дребно 7021/7022, доставка 7034). Профил:
  `backend/seed/prompts/stroymarket.md`.

## Структура

```
docker-compose.yml          # целият стек
docker-compose.gpu.yml      # override за NVIDIA GPU
backend/
  app/
    main.py, api.py         # FastAPI
    worker.py               # фонов обработчик на опашката
    models.py, schemas.py   # SQLAlchemy / Pydantic
    chart_of_accounts.py    # сметкоплан
    services/
      pdf_text.py           # PDF → текст / OCR
      llm.py                # Ollama клиент
      extraction.py         # промпт + JSON схема
      normalize.py          # нормализация, проверки, посока
      accounting.py         # правила за контиране
      xml_export.py         # XML + XSD валидация
      processing.py         # pipeline
    xml/accounting_export_v1.xsd
    tools/make_samples.py   # примерни PDF фактури
  seed/                     # демо фирми и техните промптове
  tests/
frontend/                   # React + Vite, сервиран от nginx
```

## Следващи стъпки (препоръки)

- Alembic миграции вместо `create_all`.
- Автентикация и потребители (счетоводители), одит лог на корекциите.
- Протокол по чл. 117 ЗДДС за обратно начисляване. Отделна обработка на ДДС без право на
  данъчен кредит (представителни разходи, горива за леки автомобили).
- Курсове на БНБ/ЕЦБ за валути извън EUR/BGN.
- Банкови извлечения за статиите по плащанията (401/411 ↔ 503).
- Few-shot примери: одобрените документи на фирмата като примери в промпта.
- Vision модел (например `qwen2.5vl`) за лоши сканове вместо OCR.
