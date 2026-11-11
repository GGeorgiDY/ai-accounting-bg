"""Фонов worker: взима документи от опашката (таблица documents, status=queued).

Използва SELECT ... FOR UPDATE SKIP LOCKED, така че могат да се пуснат
няколко worker-а паралелно (docker compose up --scale worker=2).
"""
import logging
import signal
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.config import settings
from app.db import SessionLocal, wait_for_db
from app.models import DocStatus, Document
from app.services import llm
from app.services.llm import LLMUnavailable
from app.services.processing import process_document

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [worker] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("worker")

_running = True
_busy = False


class Shutdown(BaseException):
    pass


def _stop(*_):
    global _running
    _running = False
    log.info("Shutdown requested")
    if _busy:  # прекъсваме дългата LLM заявка; документът се връща в опашката
        raise Shutdown()


def requeue_stale() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.stale_processing_minutes)
    with SessionLocal() as db:
        n = db.execute(
            update(Document)
            .where(Document.status == DocStatus.PROCESSING, Document.processing_started_at < cutoff)
            .values(status=DocStatus.QUEUED)
        ).rowcount
        db.commit()
        if n:
            log.warning("Requeued %d stale documents", n)


def claim_next() -> int | None:
    with SessionLocal() as db:
        doc = db.execute(
            select(Document)
            .where(Document.status == DocStatus.QUEUED)
            .order_by(Document.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()
        if doc is None:
            return None
        doc.status = DocStatus.PROCESSING
        doc.processing_started_at = datetime.now(timezone.utc)
        doc.attempts += 1
        db.commit()
        return doc.id


def handle(doc_id: int) -> None:
    global _busy
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        if doc is None:
            return
        started = time.monotonic()
        try:
            _busy = True
            try:
                process_document(doc)
            finally:
                _busy = False
            log.info("Document #%d -> %s (%.1fs)", doc.id, doc.status, time.monotonic() - started)
        except Shutdown:
            db.rollback()
            db.execute(update(Document).where(Document.id == doc_id)
                       .values(status=DocStatus.QUEUED, attempts=Document.attempts - 1))
            db.commit()
            log.info("Document #%d returned to queue", doc_id)
            return
        except LLMUnavailable as exc:
            log.warning("LLM unavailable for #%d: %s", doc.id, exc)
            doc.status = DocStatus.QUEUED if doc.attempts < settings.worker_max_attempts else DocStatus.FAILED
            doc.error = str(exc)
            db.commit()
            time.sleep(15)
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("Document #%d failed", doc.id)
            doc.status = DocStatus.FAILED
            doc.error = f"{exc.__class__.__name__}: {exc}"
        db.commit()


def wait_for_model() -> None:
    last = None
    while _running:
        st = llm.status()
        if st["model_ready"]:
            log.info("LLM model %s is ready", st["model"])
            return
        msg = "Ollama unreachable" if not st["reachable"] else f"waiting for model {st['model']} to be pulled"
        if msg != last:
            log.info(msg)
            last = msg
        time.sleep(10)


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    wait_for_db()
    wait_for_model()
    requeue_stale()
    log.info("Worker started (model=%s)", settings.llm_model)
    last_stale_check = time.monotonic()
    while _running:
        if time.monotonic() - last_stale_check > 300:
            requeue_stale()
            last_stale_check = time.monotonic()
        doc_id = claim_next()
        if doc_id is None:
            time.sleep(settings.worker_poll_seconds)
            continue
        handle(doc_id)


if __name__ == "__main__":
    main()
