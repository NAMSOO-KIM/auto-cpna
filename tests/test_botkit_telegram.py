import json

import httpx
import pytest

from botkit.jobspec import TelegramSink
from botkit.sinks import telegram


def test_split_prefers_paragraph_boundary():
    first = "첫 문단" + "가" * 60          # 64자
    second = "두 번째 문단입니다. " * 4    # 상한을 넘기려고 길게
    chunks = telegram.split_message(f"{first}\n\n{second}", limit=80)
    assert chunks[0] == first
    assert chunks[1] == second.strip()


def test_split_falls_back_to_hard_cut_when_no_boundary():
    chunks = telegram.split_message("나" * 250, limit=100)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_short_message_is_not_split():
    assert telegram.split_message("짧은 보고") == ["짧은 보고"]


def test_empty_message_sends_nothing():
    assert telegram.split_message("   \n  ") == []


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.fixture
def telegram_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")


def _patch_client(monkeypatch, handler):
    original = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = _transport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(telegram.httpx, "Client", factory)


def test_send_posts_header_and_body(monkeypatch, telegram_env):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.read()))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

    _patch_client(monkeypatch, handler)
    ids = telegram.send(TelegramSink(type="telegram"), "본문", header="[머리말]")

    assert ids == [7]
    assert seen["text"].startswith("[머리말]")
    assert "본문" in seen["text"]
    assert "parse_mode" not in seen  # 기본값 none


def test_markdown_parse_error_falls_back_to_plain_text(monkeypatch, telegram_env):
    """서식 때문에 보고가 아예 안 가는 것보다, 서식을 버리고 보내는 게 낫다."""
    calls = []

    def handler(request):
        payload = json.loads(request.read())
        calls.append(payload)
        if "parse_mode" in payload:
            return httpx.Response(400, json={"description": "can't parse entities"})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

    _patch_client(monkeypatch, handler)
    ids = telegram.send(TelegramSink(type="telegram", parse_mode="Markdown"), "*깨진 서식")

    assert ids == [9]
    assert len(calls) == 2 and "parse_mode" not in calls[1]


def test_failure_message_names_the_chat_id_env(monkeypatch, telegram_env):
    def handler(request):
        return httpx.Response(403, json={"description": "bot was blocked by the user"})

    _patch_client(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="TELEGRAM_CHAT_ID"):
        telegram.send(TelegramSink(type="telegram"), "본문")


def test_missing_token_explains_how_to_get_one(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="BotFather"):
        telegram.send(TelegramSink(type="telegram"), "본문")
