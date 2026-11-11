"""Зарежда примерните компании при първи старт (ако базата е празна)."""
import json
import logging
from pathlib import Path

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Company

log = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def seed_companies() -> None:
    with SessionLocal() as db:
        if db.scalar(select(func.count(Company.id))):
            return
        items = json.loads((SEED_DIR / "companies.json").read_text(encoding="utf-8"))
        for item in items:
            prompt = (SEED_DIR / "prompts" / item.pop("prompt_file")).read_text(encoding="utf-8")
            db.add(Company(**item, ai_prompt=prompt))
        db.commit()
        log.info("Seeded %d companies", len(items))
