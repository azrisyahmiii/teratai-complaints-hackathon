"""Ops service app: `uv run fastapi run src/teratai/ops/main.py --port 8001` (CORE_URL points at the core API)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from teratai.ops import db, routes


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.init()
    yield


app = FastAPI(title="Teratai ops service", lifespan=lifespan)
app.include_router(routes.router)
