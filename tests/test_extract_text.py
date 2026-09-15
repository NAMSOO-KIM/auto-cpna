"""응답 본문 추출 규칙 검증.

content[0].text를 그대로 읽던 기존 방식은 두 가지로 깨진다: thinking 블록이
먼저 오는 모델에서는 AttributeError가 나고, max_tokens에서 잘린 응답은 제휴
고지 문구가 빠진 채로 조용히 초안이 된다.
"""
from types import SimpleNamespace

import pytest

from autocpna.content_gen.base import extract_text


def _message(blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _thinking_block():
    # display가 omitted인 모델의 thinking 블록에는 .text 자체가 없다.
    return SimpleNamespace(type="thinking", thinking="")


def test_returns_text_block_content():
    assert extract_text(_message([_text_block("본문")])) == "본문"


def test_skips_leading_thinking_block():
    message = _message([_thinking_block(), _text_block("본문")])

    assert extract_text(message) == "본문"


def test_joins_multiple_text_blocks():
    message = _message([_text_block("앞부분 "), _text_block("뒷부분")])

    assert extract_text(message) == "앞부분 뒷부분"


def test_raises_when_truncated_at_max_tokens():
    message = _message([_text_block("잘린 본문")], stop_reason="max_tokens")

    with pytest.raises(RuntimeError, match="잘렸습니다"):
        extract_text(message)


def test_raises_when_no_text_block():
    message = _message([_thinking_block()], stop_reason="end_turn")

    with pytest.raises(RuntimeError, match="text 블록이 없습니다"):
        extract_text(message)
