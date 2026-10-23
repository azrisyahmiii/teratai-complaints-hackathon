"""FastAPI app: the organisers' API (routes_agent), our UI read API (routes_ui) and the predictions export."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from teratai.api import routes_agent, routes_export, routes_ui, worker


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    worker.warm_up()
    yield
    worker.shutdown()


app = FastAPI(title="Teratai complaints agent", lifespan=lifespan)
app.include_router(routes_agent.router)
app.include_router(routes_export.router)
app.include_router(routes_ui.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

