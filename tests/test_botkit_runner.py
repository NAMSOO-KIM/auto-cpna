import datetime as dt

import pytest

from botkit import runner, state
from botkit.jobspec import parse_job

NOW = dt.datetime(2026, 9, 21, 23, 5, tzinfo=dt.timezone.utc)  # KST 09-22 08:05

JOB = {
    "title": "테스트 봇",
    "schedule": {"times": ["08:00"]},
    "source": {"type": "static", "rows": [{"문의": "배송 언제 오나요"}]},
    "prompt": {"system": "시스템", "user_template": "{rows}"},
    "sinks": [{"type": "telegram"}],
}


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def generate(job, rows, now, client=None):
        calls.append((job.name, len(rows)))
        return f"{job.name} 보고서"

    monkeypatch.setattr(runner.llm, "generate", generate)
    return calls


@pytest.fixture
def sent(monkeypatch):
    delivered = []

    def deliver(job, text, now):
        delivered.append((job.name, text))
        return ["telegram: 1개 메시지 발송"]

    monkeypatch.setattr(runner, "deliver", deliver)
    return delivered


def test_run_job_collects_generates_and_delivers(fake_llm, sent):
    result = runner.run_job(parse_job("acme", JOB), now=NOW)
    assert (result.status, result.row_count) == ("ok", 1)
    assert sent == [("acme", "acme 보고서")]


def test_dry_run_does_not_deliver(fake_llm, sent):
    result = runner.run_job(parse_job("acme", JOB), dry_run=True, now=NOW)
    assert result.status == "dry-run"
    assert result.output == "acme 보고서"
    assert sent == []


def test_empty_collection_skips_before_spending_api_budget(fake_llm, sent):
    spec = parse_job("acme", JOB)
    spec.source.rows = []
    # static 소스는 min_length=1이라 런타임에서 비우고 확인한다.
    result = runner.run_job(spec, now=NOW)
    assert result.status == "skipped"
    assert fake_llm == [] and sent == []


def test_skip_when_empty_false_still_reports(fake_llm, sent):
    spec = parse_job("acme", {**JOB, "skip_when_empty": False})
    spec.source.rows = []
    assert runner.run_job(spec, now=NOW).status == "ok"


def test_run_due_only_runs_scheduled_jobs(fake_llm, sent):
    morning = parse_job("morning", JOB)
    evening = parse_job("evening", {**JOB, "schedule": {"times": ["18:00"]}})

    results = runner.run_due([morning, evening], now=NOW, tick_minutes=60)
    assert [(r.job_name, r.status) for r in results] == [("morning", "ok")]


def test_disabled_job_is_ignored(fake_llm, sent):
    job = parse_job("acme", {**JOB, "enabled": False})
    assert runner.run_due([job], now=NOW, tick_minutes=60) == []


def test_one_failing_job_does_not_stop_the_others(monkeypatch, sent):
    def generate(job, rows, now, client=None):
        if job.name == "broken":
            raise RuntimeError("시트 공유 설정이 풀렸습니다")
        return "보고서"

    monkeypatch.setattr(runner.llm, "generate", generate)
    jobs = [parse_job("broken", JOB), parse_job("healthy", JOB)]

    results = {r.job_name: r for r in runner.run_due(jobs, now=NOW, tick_minutes=60)}
    assert results["broken"].failed
    assert "시트 공유" in results["broken"].reason
    assert results["healthy"].status == "ok"


def test_state_file_prevents_double_send_in_same_window(tmp_path, fake_llm, sent):
    path = tmp_path / "state.json"
    jobs = [parse_job("acme", JOB)]

    runner.run_due(jobs, now=NOW, tick_minutes=60, state_path=path)
    # 같은 08:00 회차에 스케줄이 한 번 더 깨어난 상황
    second = runner.run_due(jobs, now=NOW + dt.timedelta(minutes=20), tick_minutes=60, state_path=path)

    assert len(sent) == 1
    assert second[0].status == "skipped" and "이미 발송" in second[0].reason


def test_failed_job_is_retried_on_next_tick(tmp_path, monkeypatch, sent):
    attempts = []

    def generate(job, rows, now, client=None):
        attempts.append(now)
        if len(attempts) == 1:
            raise RuntimeError("일시적 네트워크 오류")
        return "보고서"

    monkeypatch.setattr(runner.llm, "generate", generate)
    path = tmp_path / "state.json"
    jobs = [parse_job("acme", JOB)]

    runner.run_due(jobs, now=NOW, tick_minutes=60, state_path=path)
    retry = runner.run_due(jobs, now=NOW + dt.timedelta(minutes=20), tick_minutes=60, state_path=path)

    assert retry[0].status == "ok"
    assert not state.load_state(path) == {}


def test_dry_run_never_writes_state(tmp_path, fake_llm, sent):
    path = tmp_path / "state.json"
    runner.run_due([parse_job("acme", JOB)], now=NOW, tick_minutes=60, state_path=path, dry_run=True)
    assert not path.exists()
