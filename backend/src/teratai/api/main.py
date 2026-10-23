"""FastAPI app. P4a minimal: health + stub intake and case reads so the OpenAPI types exist; P1 replaces the stubs."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from teratai import pipeline
from teratai.api import routes_agent, worker
from teratai.api.schemas import CaseCreated, CaseDetail, CaseSummary
from teratai.models import ComplaintRow


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    worker.warm_up()
    yield
    worker.shutdown()


app = FastAPI(title="Teratai complaints agent", lifespan=lifespan)
app.include_router(routes_agent.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/complaints", status_code=202)
def create_complaint(row: ComplaintRow) -> CaseCreated:
    decision = pipeline.process_complaint(row, run_id="live")
    case_id = pipeline.store(row, decision)
    return CaseCreated(case_id=case_id, complaint_id=decision.complaint_id, existing=False)


@app.get("/api/cases")
def list_cases() -> list[CaseSummary]:
    return []


@app.get("/api/cases/{case_id}")
def get_case(case_id: int) -> CaseDetail:
    raise HTTPException(status_code=404, detail=f"case {case_id} not found")
