import datetime as dt
import json

from botkit import state

FIRE_AT = dt.datetime(2026, 9, 21, 8, 0, tzinfo=dt.timezone(dt.timedelta(hours=9)))


def test_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    state.save_state(path, state.mark_ran({}, "acme", FIRE_AT))
    loaded = state.load_state(path)
    assert state.already_ran(loaded, "acme", FIRE_AT)


def test_other_fire_time_is_not_marked(tmp_path):
    loaded = state.mark_ran({}, "acme", FIRE_AT)
    later = FIRE_AT + dt.timedelta(hours=6)
    assert not state.already_ran(loaded, "acme", later)


def test_corrupt_state_file_starts_empty(tmp_path):
    """캐시가 깨져도 스케줄 전체가 멈추면 안 된다 (최악의 경우 1회 중복 발송)."""
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    assert state.load_state(path) == {}


def test_missing_parent_directory_is_created(tmp_path):
    path = tmp_path / "nested" / "state.json"
    state.save_state(path, {"acme": FIRE_AT.isoformat()})
    assert json.loads(path.read_text(encoding="utf-8"))["acme"] == FIRE_AT.isoformat()
