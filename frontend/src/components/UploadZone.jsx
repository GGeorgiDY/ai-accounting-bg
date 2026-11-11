import { useRef, useState } from "react";
import { api } from "../api.js";

export default function UploadZone({ companyId, onUploaded }) {
  const input = useRef(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState([]);

  const upload = async (fileList) => {
    const files = [...fileList];
    if (!files.length) return;
    setBusy(true);
    setMessages([]);
    try {
      const { results } = await api.upload(companyId, files);
      setMessages(results.filter((r) => r.error).map((r) => `${r.filename}: ${r.error}`));
      onUploaded();
    } catch (e) {
      setMessages([e.message]);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  return (
    <div>
      <div
        className={`dropzone ${drag ? "drag" : ""}`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          upload(e.dataTransfer.files);
        }}
      >
        <input ref={input} type="file" accept="application/pdf,.pdf" multiple hidden onChange={(e) => upload(e.target.files)} />
        <div className="dz-icon">⬆</div>
        <div>
          <strong>{busy ? "Качване…" : "Пуснете PDF фактури тук"}</strong> или кликнете, за да изберете
        </div>
        <div className="muted small">Може няколко файла наведнъж. Сканираните документи се разпознават с OCR.</div>
      </div>
      {messages.map((m) => (
        <div key={m} className="alert warn">
          {m}
        </div>
      ))}
    </div>
  );
}
