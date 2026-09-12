import hashlib

import httpx
import pytest

from autocpna.media_gen.cloudinary_uploader import CloudinaryUploader


@pytest.fixture
def uploader(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDINARY_CLOUD_NAME", "demo-cloud")
    monkeypatch.setenv("CLOUDINARY_API_KEY", "demo-key")
    monkeypatch.setenv("CLOUDINARY_API_SECRET", "demo-secret")
    from autocpna.config import get_settings

    get_settings.cache_clear()
    return CloudinaryUploader()


def _image_file(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"fake-png-bytes")
    return path


def _mock(monkeypatch, handler):
    real_client_cls = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client_cls(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("autocpna.media_gen.cloudinary_uploader.httpx.Client", fake_client)


def test_configured_reflects_credentials(uploader):
    assert uploader.configured is True


def test_not_configured_without_credentials(monkeypatch):
    from autocpna.config import get_settings

    get_settings.cache_clear()
    assert CloudinaryUploader().configured is False


def test_upload_returns_secure_url_and_signs_correctly(uploader, monkeypatch, tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        body = request.content.decode("utf-8", errors="ignore")
        captured["body"] = body
        return httpx.Response(
            200, json={"secure_url": "https://res.cloudinary.com/demo-cloud/image/upload/v1/foo.png"}
        )

    _mock(monkeypatch, handler)

    image_path = _image_file(tmp_path)
    result = uploader.upload(str(image_path), folder="autocpna-test")

    assert result == "https://res.cloudinary.com/demo-cloud/image/upload/v1/foo.png"
    assert captured["url"] == "https://api.cloudinary.com/v1_1/demo-cloud/image/upload"
    assert "autocpna-test" in captured["body"]
    assert "demo-key" in captured["body"]


def test_signature_matches_manual_computation(uploader, monkeypatch, tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8", errors="ignore")
        return httpx.Response(200, json={"secure_url": "https://example.com/x.png"})

    _mock(monkeypatch, handler)

    uploader.upload(str(_image_file(tmp_path)), folder="autocpna")

    import re

    timestamp = re.search(r'name="timestamp"\s*\r?\n\r?\n(\d+)', captured["body"]).group(1)
    signature = re.search(r'name="signature"\s*\r?\n\r?\n([0-9a-f]+)', captured["body"]).group(1)

    expected = hashlib.sha1(
        f"folder=autocpna&timestamp={timestamp}demo-secret".encode("utf-8")
    ).hexdigest()
    assert signature == expected
