"""Sim–Real routes: connector vocabulary, workflow compilation and kept run reports.

Compiling plans paths and checks commands; it starts nothing. A run happens where the
connectors are installed (`ops/sim-real`), and its report is kept here once it is shown
to belong to a plan compiled against the pinned connector releases.
"""

import time
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from ..auth import identify
from ..models import StrictModel
from ..store import Write
from . import bindings, compiler, report

PREFIX = "simreal-run#"
MAX_RUNS = 50
router = APIRouter(prefix="/api/sim-real/v1")


class KeepRun(StrictModel):
    run_id: UUID = Field(default_factory=uuid4)
    plan: dict
    report: dict


@router.get("/connectors")
def connectors(_owner: str = Depends(identify)):
    return {"evidence": compiler.EVIDENCE, "connectors": bindings.catalog()}


@router.get("/example")
def example(_owner: str = Depends(identify)):
    return compiler.example()


@router.post("/compile")
def compile_workflow(data: compiler.Workflow, _owner: str = Depends(identify)):
    return compiler.compile_workflow(data)


@router.post("/runs", status_code=201)
def keep(data: KeepRun, request: Request, owner: str = Depends(identify)):
    store = request.app.state.store
    key = PREFIX + str(data.run_id)
    existing = store.get(owner, key)
    try:
        record = report.check(data.plan, data.report)
    except report.ReportError as exc:
        raise HTTPException(422, str(exc)) from exc
    if existing:
        if existing["plan_digest"] != record["plan_digest"]:
            raise HTTPException(409, "This run ID holds a report for another plan")
        return existing
    if len(store.partition(owner, PREFIX, MAX_RUNS)) >= MAX_RUNS:
        raise HTTPException(409, f"Keep at most {MAX_RUNS} runs; delete one first")
    record.update(run_id=str(data.run_id), version=1, kept_at=time.time())
    store.put(owner, key, record, None)
    return record


@router.get("/runs")
def runs(request: Request, owner: str = Depends(identify)):
    found = request.app.state.store.partition(owner, PREFIX, MAX_RUNS)
    return {
        "runs": sorted(
            (
                {
                    k: r.get(k)
                    for k in (
                        "run_id",
                        "name",
                        "outcome",
                        "reason",
                        "kept_at",
                        "wall_s",
                        "device_s",
                        "plan_digest",
                    )
                }
                | {"steps": len(r["steps"]), "cycles": len(r["cycles"])}
                for r in found
            ),
            key=lambda r: -(r["kept_at"] or 0),
        )
    }


@router.get("/runs/{run_id}")
def run(run_id: UUID, request: Request, owner: str = Depends(identify)):
    found = request.app.state.store.get(owner, PREFIX + str(run_id))
    if not found:
        raise HTTPException(404, "Run not found")
    return found


@router.delete("/runs/{run_id}", status_code=204)
def delete(run_id: UUID, request: Request, owner: str = Depends(identify)):
    store = request.app.state.store
    found = store.get(owner, PREFIX + str(run_id))
    if not found:
        raise HTTPException(404, "Run not found")
    store.transact([Write(owner, PREFIX + str(run_id), None, found["version"])])
