from autocpna.pipeline.orchestrator import register_manual_product


def test_register_manual_product_without_keyword(fresh_db):
    product = register_manual_product(
        name="유기농 핸드크림",
        category="뷰티",
        price=15000,
        product_url="https://shoppingconnect.naver.example/link/abc123",
        margin_rate=0.15,
        source="naver_shopping_connect",
    )

    assert product.id is not None
    assert product.source == "naver_shopping_connect"
    assert product.margin_rate == 0.15
    assert product.search_volume == 0.0
    assert product.trend_momentum == 0.0
    assert product.score > 0  # margin_rate만으로도 0보다 큰 점수가 나와야 함
    assert product.external_id.startswith("naver_shopping_connect:")


def test_register_manual_product_uses_keyword_trend(fresh_db, monkeypatch):
    def fake_fetch(self, keywords):
        return [{"keyword": keywords[0], "search_volume": 80.0, "trend_momentum": 0.5}]

    monkeypatch.setattr(
        "autocpna.ingestion.naver_datalab.NaverDatalabClient.fetch", fake_fetch
    )
    monkeypatch.setattr(
        "autocpna.pipeline.orchestrator._fetch_seasonality_fit", lambda keyword: 0.4
    )

    product = register_manual_product(
        name="핸드크림",
        category="뷰티",
        price=15000,
        product_url="https://example.com/link",
        margin_rate=0.1,
        source="naver_shopping_connect",
        keyword="핸드크림",
    )

    assert product.search_volume == 0.8
    assert product.seasonality_fit == 0.4


def test_two_manual_products_get_distinct_external_ids(fresh_db):
    p1 = register_manual_product(
        name="A", category="c", price=1000, product_url="u1", margin_rate=0.1, source="naver_shopping_connect"
    )
    p2 = register_manual_product(
        name="B", category="c", price=2000, product_url="u2", margin_rate=0.1, source="naver_shopping_connect"
    )

    assert p1.external_id != p2.external_id
