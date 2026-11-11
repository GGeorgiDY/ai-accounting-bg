import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { DIRECTION, DOC_TYPE, ErrorBox, Modal, PAYMENT, StatusBadge, money } from "./common.jsx";

const num = (v) => (v === "" || v === null || isNaN(Number(v)) ? 0 : Number(v));

function Field({ label, children }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export default function DocumentPanel({ documentId, company, onClose, onChanged }) {
  const [doc, setDoc] = useState(null);
  const [data, setData] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  const load = () =>
    api
      .document(documentId)
      .then((d) => {
        setDoc(d);
        setData(d.extracted ? structuredClone(d.extracted) : null);
        setDirty(false);
      })
      .catch(setError);

  useEffect(() => {
    load();
    api.accounts().then(setAccounts);
  }, [documentId]);

  // авто-обновяване, докато документът се обработва
  useEffect(() => {
    if (!doc || !["queued", "processing"].includes(doc.status)) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [doc?.status]);

  const accountName = useMemo(() => Object.fromEntries(accounts.map((a) => [a.code, a.name])), [accounts]);
  const lineAccounts = useMemo(() => {
    const usage = data?.direction === "sale" ? "sale" : data?.direction === "purchase" ? "purchase" : null;
    return accounts.filter((a) => (usage ? a.usage === usage : ["purchase", "sale"].includes(a.usage)));
  }, [accounts, data?.direction]);

  const update = (mutator) => {
    setData((prev) => {
      const next = structuredClone(prev);
      mutator(next);
      return next;
    });
    setDirty(true);
  };

  const run = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fn();
      if (res && res.id) {
        setDoc(res);
        setData(res.extracted ? structuredClone(res.extracted) : null);
        setDirty(false);
      }
      onChanged();
      return res;
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const save = () => {
    const payload = structuredClone(data);
    payload.lines = payload.lines.map((l) => ({
      ...l,
      quantity: num(l.quantity),
      unit_price: num(l.unit_price),
      net_amount: num(l.net_amount),
      vat_rate: num(l.vat_rate),
      vat_amount: num(l.vat_amount),
    }));
    ["net_amount", "vat_amount", "gross_amount"].forEach((k) => (payload.totals[k] = num(payload.totals[k])));
    payload.exchange_rate = payload.exchange_rate ? num(payload.exchange_rate) : null;
    return run(() => api.updateDocumentData(documentId, payload));
  };

  const remove = async () => {
    if (!confirm("Да изтрия ли документа?")) return;
    await run(() => api.deleteDocument(documentId));
    onClose();
  };

  if (!doc) {
    return (
      <Modal title="Документ" onClose={onClose} wide>
        <ErrorBox error={error} />
        <p className="muted">Зареждане…</p>
      </Modal>
    );
  }

  const processing = ["queued", "processing"].includes(doc.status);
  const counterpartyKey = data?.direction === "sale" ? "customer" : "supplier";

  return (
    <Modal title={doc.original_filename} onClose={onClose} wide>
      <div className="doc-toolbar">
        <StatusBadge status={doc.status} />
        {doc.used_ocr && <span className="badge">OCR</span>}
        {doc.llm_model && <span className="muted small">модел: {doc.llm_model}</span>}
        <span className="spacer" />
        <a className="btn" href={api.fileUrl(doc.id)} target="_blank" rel="noreferrer">
          PDF
        </a>
        {doc.journal?.length > 0 && (
          <a className="btn" href={api.xmlUrl(doc.id)}>
            XML
          </a>
        )}
        <button className="btn" disabled={busy || processing} onClick={() => run(() => api.reprocess(doc.id))}>
          ↻ Обработи отново с AI
        </button>
        <button className="btn danger" disabled={busy} onClick={remove}>
          Изтрий
        </button>
      </div>

      <ErrorBox error={error} />
      {doc.error && <div className="alert error">{doc.error}</div>}
      {processing && <div className="alert info">Документът се обработва от локалния AI модел… (на CPU може да отнеме 1–3 минути)</div>}
      {doc.warnings?.length > 0 && (
        <div className="alert warn">
          <strong>Проверете:</strong>
          <ul>
            {doc.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {data && (
        <>
          <section className="panel-section">
            <h3>Реквизити</h3>
            <div className="grid-4">
              <Field label="Вид">
                <select value={data.document_type} onChange={(e) => update((d) => (d.document_type = e.target.value))}>
                  {Object.entries(DOC_TYPE).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Посока">
                <select value={data.direction} onChange={(e) => update((d) => (d.direction = e.target.value))}>
                  {Object.entries(DIRECTION).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Номер">
                <input value={data.document_number} onChange={(e) => update((d) => (d.document_number = e.target.value))} />
              </Field>
              <Field label="Дата">
                <input type="date" value={data.issue_date} onChange={(e) => update((d) => (d.issue_date = e.target.value))} />
              </Field>
              <Field label="Валута">
                <input value={data.currency} maxLength={3} onChange={(e) => update((d) => (d.currency = e.target.value.toUpperCase()))} />
              </Field>
              <Field label="Курс към счетоводна валута">
                <input
                  value={data.exchange_rate ?? ""}
                  onChange={(e) => update((d) => (d.exchange_rate = e.target.value))}
                  placeholder="автоматично за EUR/BGN"
                />
              </Field>
              <Field label="Плащане">
                <select value={data.payment_method} onChange={(e) => update((d) => (d.payment_method = e.target.value))}>
                  {Object.entries(PAYMENT).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Увереност на AI">
                <input value={data.confidence ? `${Math.round(data.confidence * 100)}%` : "—"} disabled />
              </Field>
            </div>
            <div className="grid-2 parties">
              {["supplier", "customer"].map((key) => (
                <div key={key} className={`party ${key === counterpartyKey ? "highlight" : ""}`}>
                  <h4>{key === "supplier" ? "Доставчик" : "Получател"}</h4>
                  <input
                    value={data[key].name}
                    placeholder="Име"
                    onChange={(e) => update((d) => (d[key].name = e.target.value))}
                  />
                  <div className="grid-2">
                    <input value={data[key].eik} placeholder="ЕИК" onChange={(e) => update((d) => (d[key].eik = e.target.value))} />
                    <input
                      value={data[key].vat_number}
                      placeholder="ДДС №"
                      onChange={(e) => update((d) => (d[key].vat_number = e.target.value))}
                    />
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="panel-section">
            <h3>Редове и контировка</h3>
            <table className="table compact">
              <thead>
                <tr>
                  <th>Описание</th>
                  <th className="num">Основа</th>
                  <th className="num">ДДС %</th>
                  <th className="num">ДДС</th>
                  <th>Сметка</th>
                </tr>
              </thead>
              <tbody>
                {data.lines.map((l, i) => (
                  <tr key={i}>
                    <td>
                      <input value={l.description} onChange={(e) => update((d) => (d.lines[i].description = e.target.value))} />
                    </td>
                    <td className="num">
                      <input className="num" value={l.net_amount} onChange={(e) => update((d) => (d.lines[i].net_amount = e.target.value))} />
                    </td>
                    <td className="num">
                      <input className="num narrow" value={l.vat_rate} onChange={(e) => update((d) => (d.lines[i].vat_rate = e.target.value))} />
                    </td>
                    <td className="num">
                      <input className="num" value={l.vat_amount} onChange={(e) => update((d) => (d.lines[i].vat_amount = e.target.value))} />
                    </td>
                    <td>
                      <select value={l.account_code} onChange={(e) => update((d) => (d.lines[i].account_code = e.target.value))}>
                        {!lineAccounts.some((a) => a.code === l.account_code) && <option value={l.account_code}>{l.account_code || "—"}</option>}
                        {lineAccounts.map((a) => (
                          <option key={a.code} value={a.code}>
                            {a.code} {a.name}
                            {company.allowed_accounts?.length && !company.allowed_accounts.includes(a.code) ? " (извън профила)" : ""}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td className="right">Общо (основа / ДДС / сума):</td>
                  <td className="num">
                    <input className="num" value={data.totals.net_amount} onChange={(e) => update((d) => (d.totals.net_amount = e.target.value))} />
                  </td>
                  <td />
                  <td className="num">
                    <input className="num" value={data.totals.vat_amount} onChange={(e) => update((d) => (d.totals.vat_amount = e.target.value))} />
                  </td>
                  <td>
                    <input className="num" value={data.totals.gross_amount} onChange={(e) => update((d) => (d.totals.gross_amount = e.target.value))} />
                  </td>
                </tr>
              </tfoot>
            </table>
            {data.notes && <p className="muted small">Бележки от AI: {data.notes}</p>}
          </section>

          <section className="panel-section">
            <h3>Счетоводни статии {dirty && <span className="muted small">(ще се преизчислят при запис)</span>}</h3>
            {doc.journal?.length ? (
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Дт</th>
                    <th>Кт</th>
                    <th className="num">Сума</th>
                    <th>Описание</th>
                  </tr>
                </thead>
                <tbody>
                  {doc.journal.map((e, i) => (
                    <tr key={i}>
                      <td title={accountName[e.debit]}>
                        <code>{e.debit}</code> <span className="muted small">{accountName[e.debit]}</span>
                      </td>
                      <td title={accountName[e.credit]}>
                        <code>{e.credit}</code> <span className="muted small">{accountName[e.credit]}</span>
                      </td>
                      <td className="num">{money(e.amount)}</td>
                      <td className="small">{e.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">Няма генерирани статии.</p>
            )}
          </section>

          <div className="actions sticky">
            <button className="btn" disabled={!dirty || busy} onClick={load}>
              Отмени промените
            </button>
            <button className="btn primary" disabled={!dirty || busy} onClick={save}>
              Запази и преизчисли
            </button>
            <button
              className="btn success"
              disabled={dirty || busy || !doc.journal?.length || doc.status === "approved"}
              onClick={() => run(() => api.approve(doc.id))}
            >
              ✓ Одобри
            </button>
          </div>
        </>
      )}

      {doc.raw_text && (
        <details className="raw">
          <summary>Извлечен текст от PDF</summary>
          <pre>{doc.raw_text}</pre>
        </details>
      )}
    </Modal>
  );
}
