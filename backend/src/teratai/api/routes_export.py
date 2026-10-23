"""GET /api/export/predictions: predictions.csv from the agent's immutable decisions."""

import io

from fastapi import APIRouter, Query
from fastapi.responses import Response

from teratai import export

router = APIRouter()


@router.get("/api/export/predictions")
def predictions(run_id: str = Query(...)) -> Response:
    buf = io.StringIO()
    n = export.write_csv(run_id, buf)
    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=predictions-{run_id}.csv",
            "X-Rows": str(n),
        },
    )
