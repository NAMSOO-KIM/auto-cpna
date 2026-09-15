"""한 채널 생성이 실패해도 나머지 채널 초안은 살아남아야 한다.

실제로 `autocpna generate`를 돌렸을 때 instagram의 이미지 생성이
httpx.ProxyError로 죽으면서 그 상품의 threads/naver_blog/facebook 초안까지
통째로 날아갔다(커밋이 마지막에 한 번뿐이라 이미 과금된 생성 결과도 버려짐).
"""
import anthropic
import httpx
import pytest

from autocpna.db import get_session
from autocpna.models.content_draft import ContentDraft
from autocpna.models.product import Product
from autocpna.pipeline import orchestrator
from autocpna.pipeline.orchestrator import generate_drafts


def _make_product() -> Product:
    with get_session() as session:
        product = Product(external_id="ext-1", name="상품", category="cat", price=1000)
        session.add(product)
        session.commit()
        session.refresh(product)
        return product


def _fail_only(failing_channel: str, exc: Exception):
    def fake_generate_channel_content(product, channel, feedback=""):
        if channel == failing_channel:
            raise exc
        return f"{channel} 본문", ""

    return fake_generate_channel_content


def test_failing_channel_does_not_discard_other_channels(fresh_db, monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "_generate_channel_content",
        _fail_only("instagram", httpx.ProxyError("403 Forbidden")),
    )
    product = _make_product()

    result = generate_drafts(product, channels=["instagram", "threads", "facebook"])

    assert {d.channel for d in result.drafts} == {"threads", "facebook"}
    assert "instagram" in result.failures
    assert "403 Forbidden" in result.failures["instagram"]

    with get_session() as session:
        saved = session.query(ContentDraft).filter(ContentDraft.product_id == product.id).all()
        assert {d.channel for d in saved} == {"threads", "facebook"}


def test_failure_in_last_channel_still_saves_earlier_ones(fresh_db, monkeypatch):
    """실패 채널이 목록 뒤쪽이면, 앞에서 이미 성공한(=과금된) 생성분이 저장돼야 한다."""
    monkeypatch.setattr(
        orchestrator,
        "_generate_channel_content",
        _fail_only("facebook", httpx.ConnectError("boom")),
    )
    product = _make_product()

    result = generate_drafts(product, channels=["threads", "facebook"])

    assert [d.channel for d in result.drafts] == ["threads"]
    assert "facebook" in result.failures


def test_truncated_body_is_reported_as_channel_failure(fresh_db, monkeypatch):
    """content_gen이 잘린 본문에 대해 던지는 RuntimeError도 채널 실패로 잡힌다."""
    monkeypatch.setattr(
        orchestrator,
        "_generate_channel_content",
        _fail_only("naver_blog", RuntimeError("생성 본문이 max_tokens에서 잘렸습니다")),
    )
    product = _make_product()

    result = generate_drafts(product, channels=["naver_blog", "threads"])

    assert [d.channel for d in result.drafts] == ["threads"]
    assert "잘렸습니다" in result.failures["naver_blog"]


def test_anthropic_api_error_is_reported_as_channel_failure(fresh_db, monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "_generate_channel_content",
        _fail_only("threads", anthropic.APIConnectionError(request=httpx.Request("POST", "/"))),
    )
    product = _make_product()

    result = generate_drafts(product, channels=["threads", "facebook"])

    assert [d.channel for d in result.drafts] == ["facebook"]
    assert "threads" in result.failures


def test_programming_errors_are_not_swallowed(fresh_db, monkeypatch):
    """코드 버그(KeyError 등)는 채널 실패로 묻지 않고 그대로 터뜨려야 한다."""
    monkeypatch.setattr(
        orchestrator,
        "_generate_channel_content",
        _fail_only("threads", KeyError("product_url")),
    )
    product = _make_product()

    with pytest.raises(KeyError):
        generate_drafts(product, channels=["threads"])
