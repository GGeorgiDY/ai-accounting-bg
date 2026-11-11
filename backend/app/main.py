import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.db import init_db
from app.seed import seed_companies

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [api] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_companies()
    yield


app = FastAPI(title="AccountantAI", version="0.1.0", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(router)
