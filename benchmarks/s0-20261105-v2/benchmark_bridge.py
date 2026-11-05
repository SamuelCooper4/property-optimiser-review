"""S0 synthetic worker adapter. All financial work delegates to the lab authority."""

from __future__ import annotations

import gc
import hashlib
import json
from decimal import Decimal
from typing import Any

import lab

JOBS: dict[str, dict[str, Any]] = {}


def envelope(result: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Attach exact identity and authority-produced display strings for the harness."""
    raw = json.dumps(
        {"request": request, "result": result}, sort_keys=True, separators=(",", ":")
    )
    display = {}
    if result.get("status") == "ok" and "target" in result:
        row = (
            result["view"] if request.get("operation") == "scrub" else result["target"]
        )
        display = {"deposit": lab.money(Decimal(result["deposit"]))}
        for name in ("position", "debt", "investment", "cash"):
            display[name] = (
                "Unavailable" if row[name] is None else lab.money(Decimal(row[name]))
            )
    return {
        "result": result,
        "snapshot": hashlib.sha256(raw.encode()).hexdigest(),
        "display": display,
        "model": lab.VERSION,
    }


def calculate(raw: str) -> str:
    """Evaluate one indivisible, bounded synthetic plan, never a full search."""
    request = json.loads(raw)
    if request.get("operation") not in ("select", "scrub", "compare"):
        return json.dumps({"result": {"status": "unsupported_operation"}})
    return json.dumps(envelope(lab.respond(request), request), separators=(",", ":"))


def begin(job_id: str, raw: str) -> int:
    """Start a bounded resumable search without allocating its projected schedules."""
    request = json.loads(raw)
    choices = request.get(
        "choices",
        [[str(90000 + i * 2500), n * 12] for n in (25, 30, 35) for i in range(21)],
    )
    if len(choices) > 256:
        raise ValueError("Synthetic phone profile admits at most 256 search choices")
    JOBS[job_id] = {"request": request, "choices": choices, "cursor": 0, "results": []}
    return len(choices)


def step(job_id: str) -> str:
    """Evaluate one plan and yield; only a complete search may return ranked results."""
    job = JOBS[job_id]
    request = job["request"]
    if job["cursor"] < len(job["choices"]):
        deposit, months = job["choices"][job["cursor"]]
        case = {
            **lab.default_case(),
            **request.get("case", {}),
            "deposit": deposit,
            "term_months": months,
            "deals": request.get("deals", [[months, ".04"]]),
        }
        job["results"].append(lab.project(case))
        job["cursor"] += 1
    complete = job["cursor"] == len(job["choices"])
    result = {
        "complete": complete,
        "units": job["cursor"],
        "total": len(job["choices"]),
    }
    if complete:
        result.update(envelope(lab.summarise_search(job["results"]), request))
        del JOBS[job_id]
    return json.dumps(result, separators=(",", ":"))


def discard(job_id: str) -> None:
    """Release cancelled intermediate results without publishing a partial winner."""
    JOBS.pop(job_id, None)
    gc.collect()


def job_count() -> int:
    """Return retained job count for cancellation/recovery evidence."""
    return len(JOBS)
