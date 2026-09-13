from dataclasses import dataclass

import httpx
import pytest

from autocpna.publish.facebook_publisher import FacebookPublisher
from autocpna.publish.instagram_publisher import InstagramPublisher
from autocpna.publish.threads_publisher import ThreadsPublisher


@dataclass
class FakeDraft:
    caption_or_body: str = "본문"
    hashtags: str = "#태그"
    image_path: str = ""


def _mock_client(monkeypatch, target_module, handler):
    real_client_cls = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client_cls(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(f"{target_module}.httpx.Client", fake_client)


@pytest.fixture
def ig_settings(monkeypatch):
    monkeypatch.setenv("META_PAGE_ACCESS_TOKEN", "page-token")
    monkeypatch.setenv("META_IG_BUSINESS_ID", "ig123")
    from autocpna.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def threads_settings(monkeypatch):
    monkeypatch.setenv("META_THREADS_ACCESS_TOKEN", "threads-token")
    monkeypatch.setenv("META_THREADS_USER_ID", "th123")
    monkeypatch.setenv("META_PAGE_ACCESS_TOKEN", "page-token")
    from autocpna.config import get_settings

    get_settings.cache_clear()


def test_instagram_publish_rejects_local_image_path(ig_settings):
    draft = FakeDraft(image_path="media_output/images/123.png")
    result = InstagramPublisher().publish(draft)
    assert result.success is False
    assert "공개 URL" in result.error_message


def test_instagram_publish_succeeds_with_public_url(ig_settings, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "creation-1"})
        return httpx.Response(200, json={"id": "post-1"})

    _mock_client(monkeypatch, "autocpna.publish.instagram_publisher", handler)

    draft = FakeDraft(image_path="https://example.com/image.png")
    result = InstagramPublisher().publish(draft)

    assert result.success is True
    assert result.remote_post_id == "post-1"
    assert any("/ig123/media" in c for c in calls)
    assert any("/ig123/media_publish" in c for c in calls)


def test_instagram_publish_surfaces_graph_api_error_message(ig_settings, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Invalid parameter", "code": 100}})

    _mock_client(monkeypatch, "autocpna.publish.instagram_publisher", handler)

    draft = FakeDraft(image_path="https://example.com/image.png")
    result = InstagramPublisher().publish(draft)

    assert result.success is False
    assert result.error_message == "Invalid parameter"


def test_threads_publish_uses_dedicated_threads_token(threads_settings, monkeypatch):
    captured_tokens = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_tokens.append(request.url.params["access_token"])
        if request.url.path.endswith("/threads"):
            return httpx.Response(200, json={"id": "creation-1"})
        return httpx.Response(200, json={"id": "post-1"})

    _mock_client(monkeypatch, "autocpna.publish.threads_publisher", handler)

    result = ThreadsPublisher().publish(FakeDraft())

    assert result.success is True
    assert all(token == "threads-token" for token in captured_tokens)


@pytest.fixture
def fb_settings(monkeypatch):
    monkeypatch.setenv("META_PAGE_ACCESS_TOKEN", "page-token")
    monkeypatch.setenv("META_PAGE_ID", "page123")
    from autocpna.config import get_settings

    get_settings.cache_clear()


def test_facebook_publish_posts_to_page_feed(fb_settings, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["message"] = request.url.params["message"]
        captured["token"] = request.url.params["access_token"]
        return httpx.Response(200, json={"id": "page123_post1"})

    _mock_client(monkeypatch, "autocpna.publish.facebook_publisher", handler)

    result = FacebookPublisher().publish(FakeDraft(caption_or_body="오늘의 추천템입니다."))

    assert result.success is True
    assert result.remote_post_id == "page123_post1"
    assert "/page123/feed" in captured["url"]
    assert captured["message"] == "오늘의 추천템입니다."
    assert captured["token"] == "page-token"


def test_facebook_publish_surfaces_graph_api_error_message(fb_settings, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token", "code": 190}})

    _mock_client(monkeypatch, "autocpna.publish.facebook_publisher", handler)

    result = FacebookPublisher().publish(FakeDraft())

    assert result.success is False
    assert result.error_message == "Invalid OAuth access token"
