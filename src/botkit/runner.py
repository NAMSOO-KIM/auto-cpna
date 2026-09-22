"""잡 한 건의 실행 흐름(수집 -> 생성 -> 발송)과 스케줄 기반 일괄 실행."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from botkit import history, llm, state
from botkit.jobspec import JobSpec
from botkit.pricing import load_price
from botkit.schedule import DEFAULT_TICK_MINUTES, due_at
from botkit.settings import MissingSecretError
from botkit.sinks import DeliveryError, deliver
from botkit.sources import fetch_rows


@dataclass
class RunResult:
    job_name: str
    status: str  # ok / skipped / failed / dry-run
    row_count: int = 0
    output: str = ""
    deliveries: list[str] = field(default_factory=list)
    reason: str = ""
    message_ids: list[int] = field(default_factory=list)
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    estimated_cost_usd: Decimal | None = Decimal(0)
    history_id: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "failed"


def run_job(
    job: JobSpec,
    *,
    dry_run: bool = False,
    now: dt.datetime | None = None,
    client=None,
    fire_at: dt.datetime | None = None,
) -> RunResult:
    """잡 하나를 끝까지 실행. 예외는 호출부(run_due/CLI)에서 잡는다."""
    now = now or dt.datetime.now(dt.timezone.utc)
    fire_at = fire_at or now
    if now.utcoffset() is None or fire_at.utcoffset() is None:
        raise ValueError("실행 시각에는 timezone이 필요합니다.")
    result = RunResult(job.name, "failed")
    price = None
    stage = "preflight"
    error = None
    ready = False
    try:
        if job.history.enabled:
            history.prepare(job.history.directory, fire_at)
            ready = True
            price = load_price(job.history.pricing_file, job.prompt.model)
        stage = "source"
        rows = fetch_rows(job.source)
        result.row_count = len(rows)
        if not rows and job.skip_when_empty:
            result.status = "skipped"
            result.reason = "수집 결과 0건 (skip_when_empty)"
            return result

        stage = "llm"
        result.input_tokens = result.output_tokens = None
        generated = llm.generate(job, rows, now, client=client)
        result.input_tokens = generated.input_tokens
        result.output_tokens = generated.output_tokens
        result.output = generated.text
        if dry_run:
            result.status = "dry-run"
            return result

        stage = "delivery"
        delivery = deliver(job, result.output, now)
        result.deliveries = delivery.summaries
        result.message_ids = delivery.message_ids
        result.status = "ok"
        return result
    except Exception as exc:  # noqa: BLE001 - 기록 후 원래 실패를 그대로 올린다
        error = f"{stage}:{type(exc).__name__}"
        if isinstance(exc, llm.GenerationError):
            result.input_tokens = exc.result.input_tokens
            result.output_tokens = exc.result.output_tokens
        elif isinstance(exc, MissingSecretError) and stage == "llm":
            result.input_tokens = result.output_tokens = 0
        if isinstance(exc, DeliveryError):
            result.message_ids = exc.result.message_ids
            result.deliveries = exc.result.summaries
        raise
    finally:
        if result.input_tokens is None or result.output_tokens is None:
            result.estimated_cost_usd = None
        elif price is not None:
            result.estimated_cost_usd = price.estimate(result.input_tokens, result.output_tokens)
        elif result.input_tokens or result.output_tokens:
            result.estimated_cost_usd = None
        if ready:
            record = history.HistoryRecord(
                job_name=job.name, fire_at=fire_at,
                finished_at=dt.datetime.now(dt.timezone.utc), status=result.status,
                row_count=result.row_count, input_tokens=result.input_tokens,
                output_tokens=result.output_tokens, estimated_cost_usd=result.estimated_cost_usd,
                message_ids=result.message_ids, error=error,
                skip_reason="empty" if result.status == "skipped" else None,
                model=job.prompt.model, pricing=price,
            )
            history.append(job.history.directory, record)
            result.history_id = record.history_id


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
        try:
            if state.already_ran(current, job.name, fire_at):
                result = RunResult(job.name, "skipped", reason=f"{fire_at:%Y-%m-%d %H:%M} 분은 이미 발송됨")
                if job.history.enabled:
                    history.prepare(job.history.directory, fire_at)
                    record = history.HistoryRecord(
                        job_name=job.name, fire_at=fire_at,
                        finished_at=dt.datetime.now(dt.timezone.utc), status="skipped",
                        row_count=0, skip_reason="already_ran", model=job.prompt.model,
                    )
                    history.append(job.history.directory, record)
                    result.history_id = record.history_id
                results.append(result)
                continue
            result = run_job(job, dry_run=dry_run, now=now, client=client, fire_at=fire_at)
        except Exception as exc:  # noqa: BLE001 - 잡 단위 격리가 목적
            results.append(RunResult(job.name, "failed", reason=f"{type(exc).__name__}: {exc}"))
            continue

        results.append(result)
        if not dry_run and result.status in ("ok", "skipped"):
            current = state.mark_ran(current, job.name, fire_at)

    if not dry_run:
        state.save_state(state_path, current)
    return results
