import { useEffect } from "react";

export const STATUS = {
  queued: { label: "В опашката", cls: "s-queued" },
  processing: { label: "Обработва се", cls: "s-processing" },
  processed: { label: "Обработен", cls: "s-processed" },
  needs_review: { label: "За преглед", cls: "s-review" },
  approved: { label: "Одобрен", cls: "s-approved" },
  failed: { label: "Грешка", cls: "s-failed" },
};

export const DIRECTION = { purchase: "Покупка", sale: "Продажба", unknown: "Неясно" };
export const DOC_TYPE = {
  invoice: "Фактура",
  credit_note: "Кредитно известие",
  debit_note: "Дебитно известие",
  proforma: "Проформа",
  other: "Друг",
};
export const PAYMENT = { bank: "Банка", cash: "В брой", card: "Карта", other: "Друго", unknown: "Неизвестно" };

export function StatusBadge({ status }) {
  const s = STATUS[status] || { label: status, cls: "" };
  return <span className={`badge ${s.cls}`}>{s.label}</span>;
}

export function money(value, currency) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  const s = n.toLocaleString("bg-BG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${s} ${currency}` : s;
}

export function dateBg(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

export function Modal({ title, onClose, children, wide }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={onClose}>
      <div className={`modal ${wide ? "wide" : ""}`} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Затвори">
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="alert error">{String(error.message || error)}</div>;
}
