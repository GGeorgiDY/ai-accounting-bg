import { useEffect, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { api } from "./api.js";
import CompaniesPage from "./pages/CompaniesPage.jsx";
import CompanyPage from "./pages/CompanyPage.jsx";

function HealthBadge() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .health()
        .then((h) => alive && (setHealth(h), setError(false)))
        .catch(() => alive && setError(true));
    load();
    const t = setInterval(load, 10000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (error) return <span className="health bad">API недостъпно</span>;
  if (!health) return null;
  const { llm, queue } = health;
  const pending = (queue.queued || 0) + (queue.processing || 0);
  let cls = "ok";
  let label = `AI: ${llm.model}`;
  if (!llm.reachable) [cls, label] = ["bad", "AI сървърът стартира…"];
  else if (!llm.model_ready) [cls, label] = ["warn", `Моделът ${llm.model} се изтегля…`];
  return (
    <span className={`health ${cls}`} title={llm.error || ""}>
      <span className="dot" /> {label}
      {pending > 0 && <span className="queue">· {pending} в опашката</span>}
    </span>
  );
}

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="logo">∑</span> Счетоводна кантора <span className="muted">· AI осчетоводяване</span>
        </Link>
        <HealthBadge />
      </header>
      <main className="content">
        <Routes>
          <Route path="/" element={<CompaniesPage />} />
          <Route path="/companies/:id" element={<CompanyPage />} />
          <Route path="*" element={<p>Страницата не е намерена.</p>} />
        </Routes>
      </main>
    </div>
  );
}
