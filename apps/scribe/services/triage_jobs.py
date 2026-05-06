"""Tiny in-memory job registry for Triage runs.

Triage backends (especially MMS / Omni-ASR on CPU) can take 30 seconds to
several minutes per call. Running them inside the request handler ties up
gunicorn workers and gives the user a frozen browser. Instead we spawn a
worker thread, return a job_id immediately, and poll for status.

This is intentionally simple — single-process, in-memory dict, no persistence.
Adequate for the single-server pilot. When you scale to multiple workers,
swap this for Celery / Django-Q.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class TriageJob:
    job_id: str
    backend: str
    device: str
    status: str = "pending"   # pending | running | done | error | cancelled
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    stage: str = "queued"     # human-readable progress hint
    started_at: float = 0.0
    finished_at: float = 0.0

    def elapsed_ms(self) -> int:
        end = self.finished_at if self.finished_at else time.perf_counter()
        if not self.started_at:
            return 0
        return int((end - self.started_at) * 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "backend": self.backend,
            "device": self.device,
            "status": self.status,
            "stage": self.stage,
            "elapsed_ms": self.elapsed_ms(),
            "result": self.result,
            "error": self.error,
        }


_LOCK = threading.Lock()
_JOBS: dict[str, TriageJob] = {}
_THREADS: dict[str, threading.Thread] = {}


def submit(backend: str, device: str, target: Callable[[TriageJob], None]) -> TriageJob:
    job = TriageJob(
        job_id=secrets.token_urlsafe(8),
        backend=backend,
        device=device,
        status="pending",
        stage="queued",
    )
    with _LOCK:
        _JOBS[job.job_id] = job

    def _runner():
        job.status = "running"
        job.started_at = time.perf_counter()
        try:
            target(job)
            if job.status == "running":
                job.status = "done"
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = str(exc)
        finally:
            job.finished_at = time.perf_counter()

    t = threading.Thread(target=_runner, daemon=True)
    _THREADS[job.job_id] = t
    t.start()
    return job


def get(job_id: str) -> TriageJob | None:
    with _LOCK:
        return _JOBS.get(job_id)


def reap_old(max_age_seconds: int = 3600) -> int:
    """Drop completed jobs older than max_age. Call occasionally to bound memory."""
    now = time.perf_counter()
    drop: list[str] = []
    with _LOCK:
        for jid, job in _JOBS.items():
            if job.finished_at and (now - job.finished_at) > max_age_seconds:
                drop.append(jid)
        for jid in drop:
            _JOBS.pop(jid, None)
            _THREADS.pop(jid, None)
    return len(drop)
