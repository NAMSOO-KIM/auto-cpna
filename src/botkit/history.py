"""DB 없이 월별 JSONL 실행 장부를 남긴다. 원문/시크릿은 저장하지 않는다."""
from __future__ import annotations

import datetime as dt
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator

from botkit.jobspec import Strict
from botkit.pricing import ModelPrice


class HistoryError(RuntimeError):
    pass


class HistoryRecord(Strict):
    schema_version: Literal[1] = 1
    history_id: str = Field(default_factory=lambda: str(uuid4()))
    job_name: str
    fire_at: dt.datetime
    finished_at: dt.datetime
    status: Literal["ok", "skipped", "failed", "dry-run"]
    row_count: int = Field(ge=0, strict=True)
    input_tokens: int | None = Field(default=0, ge=0, strict=True)
    output_tokens: int | None = Field(default=0, ge=0, strict=True)
    estimated_cost_usd: Decimal | None = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    message_ids: list[int] = Field(default_factory=list)
    error: str | None = None
    skip_reason: Literal["empty", "already_ran"] | None = None
    model: str
    pricing: ModelPrice | None = None
    # 캐시 과금이 섞여 단가 계산 범위를 벗어난 실행. estimated_cost_usd는 None이
    # 되므로, 청구서와 대조할 때 이 건수를 먼저 본다.
    cache_tokens_seen: bool = False

    @field_validator("fire_at", "finished_at")
    @classmethod
    def _aware(cls, value: dt.datetime) -> dt.datetime:
        if value.utcoffset() is None:
            raise ValueError("이력 시각에는 timezone이 필요합니다.")
        return value


def month_path(directory: str | Path, fire_at: dt.datetime) -> Path:
    return Path(directory) / f"{fire_at.astimezone(dt.timezone.utc):%Y-%m}.jsonl"


def prepare(directory: str | Path, fire_at: dt.datetime) -> None:
    """유료 호출 전에 경로를 검사한다. 뒤늦은 디스크 오류는 append에서도 실패시킨다."""
    path = month_path(directory, fire_at)
    if os.environ.get("GITHUB_ACTIONS") == "true" and not path.resolve().is_relative_to(
        Path(".botkit").resolve()
    ):
        raise HistoryError("Actions 이력 경로는 백업되는 .botkit/ 내부로 지정하세요.")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
    except OSError as exc:
        raise HistoryError("이력 경로에 쓸 수 없습니다. history.directory 권한을 확인하세요.") from exc


def append(directory: str | Path, record: HistoryRecord) -> None:
    path = month_path(directory, record.fire_at)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(record.model_dump_json() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        # 여기서 성공을 반환하면 발송만 되고 장부는 사라지는 조용한 실패가 된다.
        raise HistoryError("이력 저장 실패. 발송 여부를 확인한 후 재실행하세요.") from exc


def read_month(directory: str | Path, month: str) -> list[HistoryRecord]:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month) or month.startswith("0000"):
        raise HistoryError("month는 YYYY-MM 형식이어야 합니다.")
    path = Path(directory) / f"{month}.jsonl"
    if not path.exists():
        return []
    records = []
    seen: dict[str, HistoryRecord] = {}
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    record = HistoryRecord.model_validate_json(line)
                    if month_path(directory, record.fire_at).stem != month:
                        raise ValueError("다른 달의 이력")
                    previous = seen.get(record.history_id)
                    if previous is not None and previous != record:
                        raise ValueError("충돌하는 이력 ID")
                except (ValueError, ValidationError) as exc:
                    raise HistoryError(
                        f"이력 {month}.jsonl:{line_number} 검증 실패. 원본 artifact를 확인하세요."
                    ) from exc
                # 누적 artifact를 합쳐도 같은 실행을 비용에 두 번 더하지 않는다.
                if previous is None:
                    records.append(record)
                    seen[record.history_id] = record
    except (OSError, UnicodeError) as exc:
        raise HistoryError("이력을 읽을 수 없습니다. 파일 권한과 UTF-8 인코딩을 확인하세요.") from exc
    return records


@dataclass
class JobTotals:
    runs: int = 0
    statuses: Counter = field(default_factory=Counter)
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal(0)
    unknown_cost_runs: int = 0


def summarize(records: list[HistoryRecord]) -> dict[str, JobTotals]:
    totals: dict[str, JobTotals] = {}
    for record in records:
        item = totals.setdefault(record.job_name, JobTotals())
        item.runs += 1
        item.statuses[record.status] += 1
        item.input_tokens += record.input_tokens or 0
        item.output_tokens += record.output_tokens or 0
        if record.estimated_cost_usd is None:
            item.unknown_cost_runs += 1
        else:
            item.estimated_cost_usd += record.estimated_cost_usd
    return totals
