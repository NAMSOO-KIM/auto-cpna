import httpx
import pytest

from autocpna.ingestion.naver_datalab import HUB_URL, LEGACY_URL, NaverDatalabClient


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("NAVER_DATALAB_CLIENT_ID", "cid")
    monkeypatch.setenv("NAVER_DATALAB_CLIENT_SECRET", "csecret")
    from autocpna.config import get_settings

    get_settings.cache_clear()


def _mock_post(monkeypatch, handler):
    real_client_cls = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client_cls(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("autocpna.ingestion.naver_datalab.httpx.Client", fake_client)


def test_fetch_defaults_to_api_hub_endpoint_and_headers(env, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"results": []})

    _mock_post(monkeypatch, handler)

    NaverDatalabClient().fetch(keywords=["무선 이어폰"])

    assert captured["url"] == HUB_URL
    assert captured["headers"]["x-ncp-apigw-api-key-id"] == "cid"
    assert captured["headers"]["x-ncp-apigw-api-key"] == "csecret"
    assert "x-naver-client-id" not in captured["headers"]


def test_legacy_endpoint_opt_in_uses_legacy_headers(env, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"results": []})

    _mock_post(monkeypatch, handler)

    NaverDatalabClient(use_legacy_endpoint=True).fetch(keywords=["무선 이어폰"])

    assert captured["url"] == LEGACY_URL
    assert captured["headers"]["x-naver-client-id"] == "cid"
    assert captured["headers"]["x-naver-client-secret"] == "csecret"


def test_fetch_parses_results_into_search_volume_and_momentum(env, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "startDate": "2026-08-01",
                "endDate": "2026-08-31",
                "timeUnit": "week",
                "results": [
                    {
                        "title": "무선 이어폰",
                        "keywords": ["무선 이어폰"],
                        "data": [
                            {"period": "2026-08-01", "ratio": 50.0},
                            {"period": "2026-08-08", "ratio": 100.0},
                        ],
                    }
                ],
            },
        )

    _mock_post(monkeypatch, handler)

    results = NaverDatalabClient().fetch(keywords=["무선 이어폰"])

    assert results == [
        {"keyword": "무선 이어폰", "search_volume": 100.0, "trend_momentum": 1.0}
    ]


def test_fetch_truncates_to_max_five_keyword_groups(env, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": []})

    _mock_post(monkeypatch, handler)

    NaverDatalabClient().fetch(keywords=[f"kw{i}" for i in range(8)])

    assert len(captured["body"]["keywordGroups"]) == 5


def test_fetch_monthly_series_returns_period_to_ratio_map(env, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "무선 이어폰",
                        "data": [
                            {"period": "2025-09-01", "ratio": 40.0},
                            {"period": "2025-10-01", "ratio": 70.0},
                        ],
                    }
                ]
            },
        )

    _mock_post(monkeypatch, handler)

    series = NaverDatalabClient().fetch_monthly_series("무선 이어폰", months=12)

    assert series == {"2025-09": 40.0, "2025-10": 70.0}
    assert captured["body"]["timeUnit"] == "month"
    assert captured["body"]["keywordGroups"] == [
        {"groupName": "무선 이어폰", "keywords": ["무선 이어폰"]}
    ]
