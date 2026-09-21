import datetime as dt

import pytest

from botkit.jobspec import ScheduleSpec
from botkit.schedule import due_at

KST = dt.timezone(dt.timedelta(hours=9))


def utc(year, month, day, hour, minute=0):
    return dt.datetime(year, month, day, hour, minute, tzinfo=dt.timezone.utc)


def test_fires_when_scheduled_time_falls_in_window():
    schedule = ScheduleSpec(times=["08:00"])
    # 08:00 KST = 23:00 UTC 전날
    fire_at = due_at(schedule, utc(2026, 9, 21, 23, 5), tick_minutes=60)
    assert fire_at is not None
    assert fire_at.astimezone(KST).hour == 8


def test_does_not_fire_outside_window():
    schedule = ScheduleSpec(times=["08:00"])
    assert due_at(schedule, utc(2026, 9, 22, 2, 0), tick_minutes=60) is None


def test_delayed_runner_still_fires_within_tick():
    """Actions 스케줄이 밀려 08:50에 깨어나도 08:00 회차는 실행돼야 한다."""
    schedule = ScheduleSpec(times=["08:00"])
    fire_at = due_at(schedule, utc(2026, 9, 21, 23, 50), tick_minutes=60)
    assert fire_at is not None and fire_at.astimezone(KST).hour == 8


def test_window_crossing_midnight_uses_previous_local_day():
    """00:10 KST 실행에서 전날 23:30 회차를 놓치지 않는다."""
    schedule = ScheduleSpec(times=["23:30"])
    fire_at = due_at(schedule, utc(2026, 9, 21, 15, 10), tick_minutes=60)
    assert fire_at is not None
    local = fire_at.astimezone(KST)
    assert (local.day, local.hour, local.minute) == (21, 23, 30)


def test_weekday_filter_uses_local_day():
    schedule = ScheduleSpec(times=["08:00"], weekdays=["mon"])
    # 2026-09-21은 월요일 -> 실행, 2026-09-20(일) -> 미실행
    assert due_at(schedule, utc(2026, 9, 20, 23, 5), tick_minutes=60) is not None
    assert due_at(schedule, utc(2026, 9, 19, 23, 5), tick_minutes=60) is None


def test_latest_time_wins_when_two_times_share_window():
    schedule = ScheduleSpec(times=["08:00", "08:30"])
    fire_at = due_at(schedule, utc(2026, 9, 21, 23, 45), tick_minutes=60)
    assert fire_at.astimezone(KST).minute == 30


@pytest.mark.parametrize("bad", ["8:0:0", "25:00", "aa:bb"])
def test_invalid_time_is_rejected_at_config_time(bad):
    with pytest.raises(ValueError):
        ScheduleSpec(times=[bad])
