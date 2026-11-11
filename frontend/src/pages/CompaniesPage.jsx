import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import CompanyForm from "../components/CompanyForm.jsx";
import { ErrorBox } from "../components/common.jsx";

function CompanyCard({ company, onClick }) {
  const s = company.stats;
  return (
    <button className="card company-card" onClick={onClick}>
      <div className="avatar">{company.name.replace(/["„“]/g, "").slice(0, 1)}</div>
      <h3>{company.name}</h3>
      <div className="muted small">ЕИК {company.eik}</div>
      {company.activity && <p className="activity">{company.activity}</p>}
      <div className="stats">
        <span title="Всички документи">📄 {s.total}</span>
        {s.queued > 0 && <span className="badge s-processing">{s.queued} в обработка</span>}
        {s.needs_review > 0 && <span className="badge s-review">{s.needs_review} за преглед</span>}
        {s.failed > 0 && <span className="badge s-failed">{s.failed} грешки</span>}
      </div>
    </button>
  );
}

export default function CompaniesPage() {
  const [companies, setCompanies] = useState(null);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const navigate = useNavigate();

  const load = () => api.companies().then(setCompanies).catch(setError);
  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Обслужвани компании</h1>
          <p className="muted">Изберете компания, за да качите и осчетоводите нейните фактури.</p>
        </div>
      </div>
      <ErrorBox error={error} />
      <div className="company-grid">
        {companies?.map((c) => (
          <CompanyCard key={c.id} company={c} onClick={() => navigate(`/companies/${c.id}`)} />
        ))}
        <button className="card add-card" onClick={() => setShowForm(true)}>
          <span className="plus">+</span>
          Добави компания
        </button>
      </div>
      {showForm && (
        <CompanyForm
          onClose={() => setShowForm(false)}
          onSaved={(c) => {
            setShowForm(false);
            navigate(`/companies/${c.id}`);
          }}
        />
      )}
    </>
  );
}
