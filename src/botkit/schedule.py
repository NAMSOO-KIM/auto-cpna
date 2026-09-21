"""고객사 타임존 기준 "지금 돌려야 할 잡인가" 판정.

GitHub Actions의 cron은 UTC 고정이고, 스케줄 실행은 러너가 붐비면 수 분에서
십수 분까지 밀린다. 그래서 워크플로는 매시 정각 한 번만 깨우고, 실제 판정은
"직전 tick_minutes 구간 안에 예정 시각이 있었는가"로 한다. 정각에 예정된 잡이
09:07에 깨어난 실행에서도 실행되게 하려는 것이다.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from botkit.jobspec import WEEKDAYS, ScheduleSpec

DEFAULT_TICK_MINUTES = 60


def due_at(
    schedule: ScheduleSpec,
    now: dt.datetime,
    tick_minutes: int = DEFAULT_TICK_MINUTES,
) -> dt.datetime | None:
    """(now - tick_minutes, now] 구간에 들어오는 가장 최근 예정 시각.

    반환값은 '몇 시 방송분인가'를 가리키는 키로도 쓴다(botkit.state가 이 값으로
    중복 실행을 막는다). 해당 구간에 예정이 없으면 None.
    """
    tz = ZoneInfo(schedule.timezone)
    local_now = now.astimezone(tz)
    window_start = local_now - dt.timedelta(minutes=tick_minutes)

    candidates: list[dt.datetime] = []
    # 구간이 자정을 넘길 수 있으므로 어제 날짜의 예정 시각도 후보에 넣는다.
    for day_offset in (0, -1):
        day = (local_now + dt.timedelta(days=day_offset)).date()
        if schedule.weekdays and WEEKDAYS[day.weekday()] not in schedule.weekdays:
            continue
        for value in schedule.times:
            hour, _, minute = value.partition(":")
            fire_at = dt.datetime(
                day.year, day.month, day.day, int(hour), int(minute), tzinfo=tz
            )
            if window_start < fire_at <= local_now:
                candidates.append(fire_at)

    return max(candidates) if candidates else None


def describe(schedule: ScheduleSpec) -> str:
    """`botkit list`에서 사람이 읽는 한 줄 요약."""
    days = "매일" if not schedule.weekdays else ",".join(schedule.weekdays)
    return f"{days} {' '.join(schedule.times)} ({schedule.timezone})"
