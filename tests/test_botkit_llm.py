import datetime as dt
import types

import pytest

from botkit import llm
from botkit.jobspec import parse_job

NOW = dt.datetime(2026, 9, 21, 23, 5, tzinfo=dt.timezone.utc)  # KST 09-22 08:05

BASE = {
    "title": "테스트 봇",
    "schedule": {"times": ["08:00"]},
    "source": {"type": "static", "rows": [{"a": 1}]},
    "prompt": {"system": "시스템", "user_template": "{date} / {row_count}건\n{rows}"},
    "sinks": [{"type": "telegram"}],
}


def message(text, stop_reason="end_turn", stop_details=None):
    block = types.SimpleNamespace(type="text", text=text)
    return types.SimpleNamespace(
        content=[block], stop_reason=stop_reason, stop_details=stop_details
    )


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.params = None
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **params):
        self.params = params
        return self.response


def test_render_leaves_unknown_braces_untouched():
    """고객 프롬프트에 섞인 JSON 예시가 KeyError로 새벽 스케줄을 죽이면 안 된다."""
    assert llm.render('{"key": {value}} / {date}', {"date": "2026-09-22"}) == (
        '{"key": {value}} / 2026-09-22'
    )


def test_rows_to_text_skips_empty_values():
    text = llm.rows_to_text([{"title": "제목", "link": ""}], max_chars=1000)
    assert "title: 제목" in text and "link" not in text


def test_rows_to_text_reports_truncation_instead_of_silently_cutting():
    rows = [{"body": "가" * 100} for _ in range(10)]
    text = llm.rows_to_text(rows, max_chars=250)
    assert "제외됨" in text


def test_build_prompt_uses_job_timezone_for_date():
    job = parse_job("t", BASE)
    prompt = llm.build_prompt(job, [{"a": 1}], NOW)
    assert prompt.startswith("2026-09-22 / 1건")


def test_generate_passes_model_and_system(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    job = parse_job("t", BASE)
    client = FakeClient(message("보고서 본문"))

    assert llm.generate(job, [{"a": 1}], NOW, client=client) == "보고서 본문"
    assert client.params["model"] == "claude-opus-5"
    assert client.params["system"] == "시스템"
    # effort를 지정하지 않으면 API 기본값을 쓰도록 아예 보내지 않는다.
    assert "output_config" not in client.params


def test_generate_sends_effort_when_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    job = parse_job("t", {**BASE, "prompt": {**BASE["prompt"], "effort": "low"}})
    client = FakeClient(message("본문"))

    llm.generate(job, [{"a": 1}], NOW, client=client)
    assert client.params["output_config"] == {"effort": "low"}


def test_truncated_response_is_not_delivered():
    with pytest.raises(RuntimeError, match="max_tokens"):
        llm.extract_text(message("앞부분만 쓰다 말았", stop_reason="max_tokens"))


def test_refusal_is_surfaced_with_category():
    refusal = message("", stop_reason="refusal", stop_details=types.SimpleNamespace(category="cyber"))
    with pytest.raises(RuntimeError, match="cyber"):
        llm.extract_text(refusal)


def test_thinking_blocks_are_skipped():
    thinking = types.SimpleNamespace(type="thinking", thinking="...")
    text = types.SimpleNamespace(type="text", text="본문")
    response = types.SimpleNamespace(
        content=[thinking, text], stop_reason="end_turn", stop_details=None
    )
    assert llm.extract_text(response) == "본문"


def test_missing_api_key_explains_where_to_put_it(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    job = parse_job("t", BASE)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm.generate(job, [{"a": 1}], NOW)
