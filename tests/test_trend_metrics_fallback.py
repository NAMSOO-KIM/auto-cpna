"""데이터랩 트렌드 조회가 실패해도 상품 등록/수집이 죽지 않아야 한다.

_fetch_seasonality_fit은 같은 API의 실패를 0.0으로 폴백하는데 트렌드 조회만
무방비라, 데이터랩이 죽으면(키 미발급/네트워크 장애) 상품 등록 자체가 예외로
터졌다 - 대시보드에서 키워드를 입력받게 되면서 사용자에게 바로 노출되는 경로다.
"""
import httpx

from autocpna.db import get_session
from autocpna.models.product import Product
from autocpna.pipeline import orchestrator
from autocpna.pipeline.orchestrator import _fetch_trend_metrics, register_manual_product


def test_returns_zeros_without_keyword():
    assert _fetch_trend_metrics("") == (0.0, 0.0)


def test_returns_zeros_when_datalab_fails(monkeypatch):
    def boom(self, keywords=None, **kw):
        raise httpx.ConnectError("datalab down")

    monkeypatch.setattr(orchestrator.NaverDatalabClient, "fetch", boom)

    assert _fetch_trend_metrics("무선 이어폰") == (0.0, 0.0)


def test_normalizes_datalab_response(monkeypatch):
    monkeypatch.setattr(
        orchestrator.NaverDatalabClient,
        "fetch",
        lambda self, keywords=None, **kw: [{"search_volume": 100.0, "trend_momentum": 200.0}],
    )

    search_volume, trend_momentum = _fetch_trend_metrics("무선 이어폰")

    assert search_volume == 1.0
    assert trend_momentum == 1.0


def test_register_manual_product_survives_datalab_outage(fresh_db, monkeypatch):
    def boom(self, keywords=None, **kw):
        raise httpx.ConnectError("datalab down")

    monkeypatch.setattr(orchestrator.NaverDatalabClient, "fetch", boom)
    monkeypatch.setattr(
        orchestrator.NaverDatalabClient,
        "fetch_monthly_series",
        lambda self, keyword, months=24: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )

    product = register_manual_product(
        name="유기농 핸드크림",
        category="뷰티",
        price=15000,
        product_url="https://example.com/1",
        margin_rate=0.15,
        source="naver_shopping_connect",
        keyword="핸드크림",
    )

    assert product.search_volume == 0.0
    assert product.trend_momentum == 0.0
    with get_session() as session:
        assert session.query(Product).count() == 1
