import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { ErrorBox, Modal } from "./common.jsx";

const EMPTY = { name: "", eik: "", vat_number: "", address: "", activity: "", ai_prompt: "", allowed_accounts: [] };

function AccountPicker({ accounts, value, onChange }) {
  const selectable = accounts.filter((a) => a.usage === "purchase" || a.usage === "sale");
  const groups = useMemo(
    () => [
      { title: "Покупки (разходи и активи)", items: selectable.filter((a) => a.usage === "purchase") },
      { title: "Продажби (приходи)", items: selectable.filter((a) => a.usage === "sale") },
    ],
    [accounts]
  );
  const set = new Set(value);
  const toggle = (code) => {
    const next = new Set(set);
    next.has(code) ? next.delete(code) : next.add(code);
    onChange([...next].sort());
  };
  return (
    <div className="account-picker">
      <p className="hint">
        Избраните сметки са единствените, които AI може да предложи за тази фирма. Ако не изберете нищо, се
        използва целият сметкоплан.
      </p>
      <div className="account-groups">
        {groups.map((g) => (
          <div key={g.title}>
            <h4>{g.title}</h4>
            {g.items.map((a) => (
              <label key={a.code} className="check">
                <input type="checkbox" checked={set.has(a.code)} onChange={() => toggle(a.code)} />
                <code>{a.code}</code> {a.name}
              </label>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function CompanyForm({ company, onClose, onSaved }) {
  const [form, setForm] = useState(company ? { ...EMPTY, ...company } : EMPTY);
  const [accounts, setAccounts] = useState([]);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.accounts().then(setAccounts).catch(setError);
    if (!company) api.promptTemplate().then((t) => setForm((f) => ({ ...f, ai_prompt: f.ai_prompt || t.template })));
  }, [company]);

  const field = (key) => ({ value: form[key] || "", onChange: (e) => setForm({ ...form, [key]: e.target.value }) });

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const body = {
      name: form.name.trim(),
      eik: form.eik.trim(),
      vat_number: form.vat_number?.trim() || null,
      address: form.address?.trim() || null,
      activity: form.activity?.trim() || null,
      ai_prompt: form.ai_prompt,
      allowed_accounts: form.allowed_accounts,
    };
    try {
      const saved = company ? await api.updateCompany(company.id, body) : await api.createCompany(body);
      onSaved(saved);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={company ? "Редакция на компания" : "Нова компания"} onClose={onClose} wide>
      <form onSubmit={submit} className="form">
        <ErrorBox error={error} />
        <div className="grid-2">
          <label>
            Име на фирмата *
            <input required {...field("name")} placeholder="Пример ЕООД" />
          </label>
          <label>
            ЕИК *
            <input required pattern="\d{9}(\d{4})?" title="9 или 13 цифри" {...field("eik")} />
          </label>
          <label>
            ДДС номер
            <input {...field("vat_number")} placeholder="BG123456789" />
          </label>
          <label>
            Адрес
            <input {...field("address")} />
          </label>
        </div>
        <label>
          Дейност
          <input {...field("activity")} placeholder="Кратко описание на дейността" />
        </label>
        <label>
          AI профил (промпт) — какви документи се очакват, типични разходи и приходи, специфики
          <textarea rows={16} className="mono" {...field("ai_prompt")} />
        </label>
        <AccountPicker
          accounts={accounts}
          value={form.allowed_accounts || []}
          onChange={(v) => setForm({ ...form, allowed_accounts: v })}
        />
        <div className="actions">
          <button type="button" className="btn" onClick={onClose}>
            Отказ
          </button>
          <button type="submit" className="btn primary" disabled={saving}>
            {saving ? "Запис…" : "Запази"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
