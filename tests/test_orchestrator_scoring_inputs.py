import httpx

from autocpna.pipeline.orchestrator import (
    _fetch_account_conversion_rate,
    _fetch_seasonality_fit,
    _host_image_publicly,
)


def test_seasonality_fit_returns_zero_without_keyword():
    assert _fetch_seasonality_fit("") == 0.0


def test_seasonality_fit_uses_monthly_series(monkeypatch):
    def fake_fetch_monthly_series(self, keyword, months=24):
        return {"2025-08": 30.0, "2025-09": 90.0, "2024-08": 20.0, "2024-09": 100.0}

    monkeypatch.setattr(
        "autocpna.ingestion.naver_datalab.NaverDatalabClient.fetch_monthly_series",
        fake_fetch_monthly_series,
    )

    score = _fetch_seasonality_fit("무선 이어폰", reference_month=9)

    assert score == 1.0  # 9월이 두 해 모두 최고치 -> 성수기


def test_seasonality_fit_falls_back_to_zero_on_http_error(monkeypatch):
    def raise_error(self, keyword, months=24):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(
        "autocpna.ingestion.naver_datalab.NaverDatalabClient.fetch_monthly_series", raise_error
    )

    assert _fetch_seasonality_fit("무선 이어폰") == 0.0


def test_account_conversion_rate_returns_client_value(monkeypatch):
    monkeypatch.setattr(
        "autocpna.ingestion.coupang_reports.CoupangReportsClient.conversion_rate",
        lambda self, start, end: 0.05,
    )

    assert _fetch_account_conversion_rate() == 0.05


def test_account_conversion_rate_returns_none_on_failure(monkeypatch):
    def raise_error(self, start, end):
        raise RuntimeError("no permission")

    monkeypatch.setattr(
        "autocpna.ingestion.coupang_reports.CoupangReportsClient.conversion_rate", raise_error
    )

    assert _fetch_account_conversion_rate() is None


def test_host_image_publicly_returns_local_path_when_not_configured(monkeypatch):
    monkeypatch.setattr(
        "autocpna.media_gen.cloudinary_uploader.CloudinaryUploader.configured",
        property(lambda self: False),
    )

    assert _host_image_publicly("media_output/images/123.png") == "media_output/images/123.png"


def test_host_image_publicly_returns_uploaded_url(monkeypatch):
    monkeypatch.setattr(
        "autocpna.media_gen.cloudinary_uploader.CloudinaryUploader.configured",
        property(lambda self: True),
    )
    monkeypatch.setattr(
        "autocpna.media_gen.cloudinary_uploader.CloudinaryUploader.upload",
        lambda self, local_path, folder="autocpna": "https://res.cloudinary.com/x/foo.png",
    )

    assert _host_image_publicly("media_output/images/123.png") == "https://res.cloudinary.com/x/foo.png"


def test_host_image_publicly_falls_back_to_local_path_on_upload_error(monkeypatch):
    monkeypatch.setattr(
        "autocpna.media_gen.cloudinary_uploader.CloudinaryUploader.configured",
        property(lambda self: True),
    )

    def raise_error(self, local_path, folder="autocpna"):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(
        "autocpna.media_gen.cloudinary_uploader.CloudinaryUploader.upload", raise_error
    )

    assert _host_image_publicly("media_output/images/123.png") == "media_output/images/123.png"
