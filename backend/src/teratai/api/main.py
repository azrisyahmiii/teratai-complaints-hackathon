"""FastAPI app: the organisers' API (routes_agent), our UI read API (routes_ui) and the predictions export."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from teratai.api import auth, routes_agent, routes_export, routes_metrics, routes_ui, worker
from teratai.ops import routes as ops_routes


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    auth.seed_users()
    worker.warm_up()
    yield
    worker.shutdown()


app = FastAPI(title="Teratai complaints agent", lifespan=lifespan)
app.include_router(routes_agent.router)
app.include_router(routes_export.router)
app.include_router(routes_ui.router)
app.include_router(auth.router)
app.include_router(ops_routes.router)
app.include_router(routes_metrics.router)


@app.middleware("http")
async def private_staff_responses(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers.append("Vary", "Cookie")
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

