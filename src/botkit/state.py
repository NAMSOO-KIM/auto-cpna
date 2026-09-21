"""마지막으로 실행한 '예정 시각'을 기록해 중복 발송을 막는다.

Actions 러너는 매번 새 컨테이너라 상태가 남지 않는다. 워크플로에서
actions/cache로 이 JSON 파일 하나만 주고받으면, 스케줄이 밀려 한 시간 안에
두 번 깨어나도 같은 '08:00분'을 두 번 보내지 않는다. 캐시가 유실되면 최악의
경우 한 번 더 보낼 뿐이라, 이 파일이 없어도 동작 자체는 막지 않는다.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


def load_state(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 캐시가 깨졌다고 스케줄 전체를 멈추진 않는다. 빈 상태로 시작하면
        # 최대 한 번 중복 발송될 뿐이다.
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path | None, state: dict[str, str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def already_ran(state: dict[str, str], job_name: str, fire_at: dt.datetime) -> bool:
    return state.get(job_name) == fire_at.isoformat()


def mark_ran(state: dict[str, str], job_name: str, fire_at: dt.datetime) -> dict[str, str]:
    return {**state, job_name: fire_at.isoformat()}
