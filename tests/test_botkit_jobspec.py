from pathlib import Path

import pytest

from botkit.jobspec import JOBS_DIR, JobConfigError, load_job, load_jobs, parse_job

MINIMAL = {
    "client_id": "ACME",  # P0-2 필수 계약. 기존 검증 내용은 유지한다.
    "title": "테스트 봇",
    "schedule": {"times": ["08:00"]},
    "source": {"type": "static", "rows": [{"a": 1}]},
    "prompt": {"system": "시스템", "user_template": "{rows}"},
    "sinks": [{"type": "telegram"}],
}


def test_name_defaults_to_file_stem():
    assert parse_job("acme", MINIMAL).name == "acme"


def test_typo_in_key_is_rejected_not_ignored():
    """`sytem:`처럼 한 글자 틀린 키가 조용히 무시되면 '프롬프트를 고쳤는데
    결과가 그대로'인 상황이 된다."""
    bad = {**MINIMAL, "prompt": {"sytem": "시스템", "user_template": "{rows}"}}
    with pytest.raises(JobConfigError, match="sytem"):
        parse_job("acme", bad)


def test_user_template_without_rows_placeholder_is_rejected():
    bad = {**MINIMAL, "prompt": {"system": "s", "user_template": "수집 결과 없이 요약해줘"}}
    with pytest.raises(JobConfigError, match="rows"):
        parse_job("acme", bad)


def test_error_message_points_at_the_offending_field():
    bad = {**MINIMAL, "schedule": {"times": ["8시"]}}
    with pytest.raises(JobConfigError, match="schedule.times"):
        parse_job("acme", bad)


def test_unknown_source_type_is_rejected():
    bad = {**MINIMAL, "source": {"type": "ftp", "path": "/x"}}
    with pytest.raises(JobConfigError):
        parse_job("acme", bad)


def test_sinks_cannot_be_empty():
    with pytest.raises(JobConfigError):
        parse_job("acme", {**MINIMAL, "sinks": []})


def test_default_model_is_opus():
    assert parse_job("acme", MINIMAL).prompt.model == "claude-opus-5"


def test_load_jobs_skips_underscore_prefixed_templates(tmp_path):
    (tmp_path / "_TEMPLATE.yaml").write_text("title: x", encoding="utf-8")
    (tmp_path / "acme.yaml").write_text(
        "title: 에이컴\n"
        "client_id: ACME\n"
        "schedule: {times: ['08:00']}\n"
        "source: {type: static, rows: [{a: 1}]}\n"
        "prompt: {system: s, user_template: '{rows}'}\n"
        "sinks: [{type: telegram}]\n",
        encoding="utf-8",
    )
    jobs = load_jobs(tmp_path)
    assert [j.name for j in jobs] == ["acme"]


def test_missing_job_lists_available_names(tmp_path):
    (tmp_path / "acme.yaml").write_text("title: x", encoding="utf-8")
    with pytest.raises(JobConfigError, match="acme"):
        load_job("nope", tmp_path)


def test_shipped_example_jobs_are_valid():
    """납품 템플릿이 깨진 채로 커밋되는 걸 막는다."""
    jobs = load_jobs(Path(JOBS_DIR))
    assert jobs, "config/jobs에 예시 잡이 없습니다"
    assert all(job.prompt.system for job in jobs)


def test_env_file_does_not_override_actions_secrets(monkeypatch, tmp_path):
    """리포지터리에 남은 옛날 .env가 Actions Secrets를 덮어쓰면 추적이 어렵다."""
    from botkit.settings import load_env_file

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# 주석\nTELEGRAM_BOT_TOKEN=\"from-file\"\nTELEGRAM_CHAT_ID=999\n잘못된줄\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "from-secrets")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    assert load_env_file(str(env_file)) == 1
    import os

    assert os.environ["TELEGRAM_BOT_TOKEN"] == "from-secrets"
    assert os.environ["TELEGRAM_CHAT_ID"] == "999"
