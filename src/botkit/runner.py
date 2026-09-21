"""잡 한 건의 실행 흐름(수집 -> 생성 -> 발송)과 스케줄 기반 일괄 실행."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from botkit import llm, state
from botkit.jobspec import JobSpec
from botkit.schedule import DEFAULT_TICK_MINUTES, due_at
from botkit.sinks import deliver
from botkit.sources import fetch_rows


@dataclass
class RunResult:
    job_name: str
    status: str  # ok / skipped / failed / dry-run
    row_count: int = 0
    output: str = ""
    deliveries: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "failed"


def run_job(
    job: JobSpec,
    *,
    dry_run: bool = False,
    now: dt.datetime | None = None,
    client=None,
) -> RunResult:
    """잡 하나를 끝까지 실행. 예외는 호출부(run_due/CLI)에서 잡는다."""
    now = now or dt.datetime.now(dt.timezone.utc)

    rows = fetch_rows(job.source)
    if not rows and job.skip_when_empty:
        return RunResult(job.name, "skipped", 0, reason="수집 결과 0건 (skip_when_empty)")

    output = llm.generate(job, rows, now, client=client)

    if dry_run:
        return RunResult(job.name, "dry-run", len(rows), output=output)

    deliveries = deliver(job, output, now)
    return RunResult(job.name, "ok", len(rows), output=output, deliveries=deliveries)


def run_due(
    jobs: list[JobSpec],
    *,
    now: dt.datetime | None = None,
    tick_minutes: int = DEFAULT_TICK_MINUTES,
    state_path: Path | None = None,
    dry_run: bool = False,
    client=None,
) -> list[RunResult]:
    """예정 시각이 직전 구간에 들어온 잡만 실행한다.

    잡 하나가 실패해도 나머지는 계속 보낸다 - 고객사 A의 시트 공유 설정이
    풀렸다고 고객사 B의 아침 보고가 같이 안 나가면 그게 더 큰 사고다.
    성공한 잡만 상태에 기록해, 실패한 잡은 다음 tick에서 다시 시도한다.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    current = state.load_state(state_path)
    results: list[RunResult] = []

    for job in jobs:
        if not job.enabled:
            continue
        fire_at = due_at(job.schedule, now, tick_minutes)
        if fire_at is None:
            continue
        if state.already_ran(current, job.name, fire_at):
            results.append(
                RunResult(job.name, "skipped", reason=f"{fire_at:%Y-%m-%d %H:%M} 분은 이미 발송됨")
            )
            continue

        try:
            result = run_job(job, dry_run=dry_run, now=now, client=client)
        except Exception as exc:  # noqa: BLE001 - 잡 단위 격리가 목적
            results.append(RunResult(job.name, "failed", reason=f"{type(exc).__name__}: {exc}"))
            continue

        results.append(result)
        if not dry_run and result.status in ("ok", "skipped"):
            current = state.mark_ran(current, job.name, fire_at)

    if not dry_run:
        state.save_state(state_path, current)
    return results
