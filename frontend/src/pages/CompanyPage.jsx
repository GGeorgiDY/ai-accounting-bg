import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import CompanyForm from "../components/CompanyForm.jsx";
import DocumentPanel from "../components/DocumentPanel.jsx";
import UploadZone from "../components/UploadZone.jsx";
import { DIRECTION, DOC_TYPE, ErrorBox, StatusBadge, dateBg, money } from "../components/common.jsx";

function ExportBar({ companyId }) {
  const [dateFrom, setFrom] = useState("");
  const [dateTo, setTo] = useState("");
  const [includeUnreviewed, setInclude] = useState(false);
  return (
    <div className="export-bar">
      <strong>Експорт в XML</strong>
      <label>
        от <input type="date" value={dateFrom} onChange={(e) => setFrom(e.target.value)} />
      </label>
      <label>
        до <input type="date" value={dateTo} onChange={(e) => setTo(e.target.value)} />
      </label>
      <label className="check">
        <input type="checkbox" checked={includeUnreviewed} onChange={(e) => setInclude(e.target.checked)} />
        включи и непрегледаните
      </label>
      <a className="btn primary" href={api.exportUrl(companyId, { dateFrom, dateTo, includeUnreviewed })}>
        ⬇ Изтегли XML
      </a>
    </div>
  );
}

function DocumentsTable({ documents, onOpen }) {
  if (!documents.length) return <p className="muted empty">Все още няма качени документи.</p>;
  return (
    <table className="table hover">
      <thead>
        <tr>
          <th>#</th>
          <th>Файл</th>
          <th>Статус</th>
          <th>Вид</th>
          <th>Номер</th>
          <th>Дата</th>
          <th>Контрагент</th>
          <th className="num">Основа</th>
          <th className="num">ДДС</th>
          <th className="num">Общо</th>
        </tr>
      </thead>
      <tbody>
        {documents.map((d) => (
          <tr key={d.id} onClick={() => onOpen(d.id)}>
            <td className="muted">{d.id}</td>
            <td className="filename" title={d.original_filename}>
              {d.original_filename}
            </td>
            <td>
              <StatusBadge status={d.status} />
              {d.warnings?.length > 0 && d.status === "needs_review" && (
                <span className="muted small"> ({d.warnings.length})</span>
              )}
            </td>
            <td>
              {d.direction && d.direction !== "unknown" && (
                <span className={`dir ${d.direction}`}>{DIRECTION[d.direction]}</span>
              )}{" "}
              <span className="muted small">{DOC_TYPE[d.doc_type] || ""}</span>
            </td>
            <td>{d.doc_number || "—"}</td>
            <td>{dateBg(d.issue_date)}</td>
            <td>{d.counterparty_name || "—"}</td>
            <td className="num">{money(d.net_amount)}</td>
            <td className="num">{money(d.vat_amount)}</td>
            <td className="num strong">{money(d.gross_amount, d.currency)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function CompanyPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [company, setCompany] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("documents");
  const [openDoc, setOpenDoc] = useState(null);
  const [editing, setEditing] = useState(false);

  const loadDocs = useCallback(() => api.documents(id).then(setDocuments).catch(setError), [id]);

  useEffect(() => {
    api.company(id).then(setCompany).catch(setError);
    loadDocs();
  }, [id, loadDocs]);

  const pending = documents.some((d) => ["queued", "processing"].includes(d.status));
  useEffect(() => {
    if (!pending) return;
    const t = setInterval(loadDocs, 3000);
    return () => clearInterval(t);
  }, [pending, loadDocs]);

  const removeCompany = async () => {
    if (!confirm(`Да изтрия ли "${company.name}" и всички нейни документи?`)) return;
    try {
      await api.deleteCompany(company.id);
      navigate("/");
    } catch (e) {
      setError(e);
    }
  };

  if (!company) return error ? <ErrorBox error={error} /> : <p className="muted">Зареждане…</p>;

  return (
    <>
      <Link to="/" className="back">
        ← Всички компании
      </Link>
      <div className="page-head">
        <div>
          <h1>{company.name}</h1>
          <p className="muted">
            ЕИК {company.eik}
            {company.vat_number && ` · ДДС № ${company.vat_number}`}
            {company.address && ` · ${company.address}`}
          </p>
          {company.activity && <p>{company.activity}</p>}
        </div>
        <div className="head-actions">
          <button className="btn" onClick={() => setEditing(true)}>
            Редактирай
          </button>
          <button className="btn danger" onClick={removeCompany}>
            Изтрий
          </button>
        </div>
      </div>
      <ErrorBox error={error} />

      <div className="tabs">
        <button className={tab === "documents" ? "active" : ""} onClick={() => setTab("documents")}>
          Документи ({documents.length})
        </button>
        <button className={tab === "profile" ? "active" : ""} onClick={() => setTab("profile")}>
          AI профил
        </button>
      </div>

      {tab === "documents" && (
        <>
          <UploadZone companyId={company.id} onUploaded={loadDocs} />
          <ExportBar companyId={company.id} />
          <DocumentsTable documents={documents} onOpen={setOpenDoc} />
        </>
      )}

      {tab === "profile" && (
        <div className="card profile">
          <div className="profile-head">
            <p className="muted">
              Този текст се подава на локалния AI модел заедно с всяка фактура на фирмата. Опишете какви документи се
              очакват, типичните разходи и приходи и към кои сметки да се отнасят.
            </p>
            <button className="btn primary" onClick={() => setEditing(true)}>
              Редактирай профила
            </button>
          </div>
          <pre className="prompt">{company.ai_prompt || "(няма профил)"}</pre>
          <h4>Позволени сметки</h4>
          <p>
            {company.allowed_accounts?.length
              ? company.allowed_accounts.map((c) => <code key={c} className="chip">{c}</code>)
              : "Целият сметкоплан"}
          </p>
        </div>
      )}

      {openDoc && (
        <DocumentPanel documentId={openDoc} company={company} onClose={() => setOpenDoc(null)} onChanged={loadDocs} />
      )}
      {editing && (
        <CompanyForm
          company={company}
          onClose={() => setEditing(false)}
          onSaved={(c) => {
            setCompany(c);
            setEditing(false);
          }}
        />
      )}
    </>
  );
}
