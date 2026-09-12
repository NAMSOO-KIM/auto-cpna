import httpx
import pytest

from autocpna.ingestion.coupang_reports import CoupangReportsClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COUPANG_PARTNERS_ACCESS_KEY", "access")
    monkeypatch.setenv("COUPANG_PARTNERS_SECRET_KEY", "secret")
    from autocpna.config import get_settings

    get_settings.cache_clear()
    return CoupangReportsClient()


def _mock(monkeypatch, handler):
    real_client_cls = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client_cls(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("autocpna.ingestion._coupang_auth.httpx.Client", fake_client)


def test_fetch_paginates_until_empty_page(client, monkeypatch):
    pages = {
        "0": [{"date": "20260901", "clickCount": 10, "orderCount": 1}],
        "1": [{"date": "20260902", "clickCount": 20, "orderCount": 2}],
        "2": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        return httpx.Response(200, json={"rCode": "0", "rMessage": "", "data": pages[page]})

    _mock(monkeypatch, handler)

    rows = client.fetch(start_date="20260901", end_date="20260902")

    assert len(rows) == 2
    assert rows[0]["clickCount"] == 10
    assert rows[1]["clickCount"] == 20


def test_conversion_rate_sums_clicks_and_orders(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        if page == "0":
            return httpx.Response(
                200,
                json={
                    "rCode": "0",
                    "rMessage": "",
                    "data": [
                        {"date": "20260901", "clickCount": 100, "orderCount": 3},
                        {"date": "20260902", "clickCount": 50, "orderCount": 2},
                    ],
                },
            )
        return httpx.Response(200, json={"rCode": "0", "rMessage": "", "data": []})

    _mock(monkeypatch, handler)

    rate = client.conversion_rate("20260901", "20260902")

    assert rate == pytest.approx(5 / 150)


def test_conversion_rate_returns_none_when_no_clicks(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rCode": "0", "rMessage": "", "data": []})

    _mock(monkeypatch, handler)

    assert client.conversion_rate("20260901", "20260902") is None


def test_fetch_raises_on_error_rcode(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rCode": "500001", "rMessage": "server error"})

    _mock(monkeypatch, handler)

    with pytest.raises(RuntimeError, match="server error"):
        client.fetch(start_date="20260901", end_date="20260902")
