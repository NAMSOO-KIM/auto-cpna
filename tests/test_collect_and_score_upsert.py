"""collect_and_score를 반복 실행해도(예: 매일 cron) 같은 상품이 중복 저장되지
않고 최신 값으로 갱신되는지 확인."""
from autocpna.db import get_session
from autocpna.models.product import Product
from autocpna.pipeline import orchestrator


def _fake_raw_product(score_input: float) -> dict:
    return {
        "external_id": "coupang-123",
        "source": "coupang_partners",
        "name": "무선 이어폰",
        "category": "이어폰",
        "price": 39000.0,
        "margin_rate": score_input,
        "product_url": "https://example.com/123",
        "image_url": "https://example.com/123.png",
    }


def _bypass_trend_and_conversion_lookups(monkeypatch) -> None:
    """min_score_threshold(0.35)를 넘기기 위해 트렌드/전환율 조회를 모두
    후하게 고정해, margin_rate 차이만으로 테스트 취지(업서트 동작)를 검증."""
    monkeypatch.setattr(
        orchestrator.NaverDatalabClient,
        "fetch",
        lambda self, keywords=None, **kw: [{"search_volume": 100.0, "trend_momentum": 200.0}],
    )
    monkeypatch.setattr(orchestrator, "_fetch_seasonality_fit", lambda keyword, reference_month=None: 1.0)
    monkeypatch.setattr(orchestrator, "_fetch_account_conversion_rate", lambda: None)


def test_rerunning_collect_and_score_updates_existing_product_instead_of_duplicating(
    fresh_db, monkeypatch
):
    _bypass_trend_and_conversion_lookups(monkeypatch)
    monkeypatch.setattr(
        orchestrator.CoupangPartnersClient, "fetch", lambda self, keyword="": [_fake_raw_product(0.1)]
    )

    first_run = orchestrator.collect_and_score(keyword="이어폰", top_n=20)
    assert len(first_run) == 1
    first_id = first_run[0].id
    first_score = first_run[0].score

    monkeypatch.setattr(
        orchestrator.CoupangPartnersClient, "fetch", lambda self, keyword="": [_fake_raw_product(0.9)]
    )
    second_run = orchestrator.collect_and_score(keyword="이어폰", top_n=20)

    assert len(second_run) == 1
    assert second_run[0].id == first_id  # 새 row가 아니라 기존 row 갱신
    assert second_run[0].score != first_score  # margin_rate가 바뀌었으니 score도 갱신됨

    with get_session() as session:
        all_products = session.query(Product).filter(Product.external_id == "coupang-123").all()
        assert len(all_products) == 1  # 중복 저장 안 됨


def test_new_external_id_still_inserts_new_product(fresh_db, monkeypatch):
    _bypass_trend_and_conversion_lookups(monkeypatch)
    monkeypatch.setattr(
        orchestrator.CoupangPartnersClient, "fetch", lambda self, keyword="": [_fake_raw_product(0.1)]
    )
    orchestrator.collect_and_score(keyword="이어폰", top_n=20)

    other_product = _fake_raw_product(0.2)
    other_product["external_id"] = "coupang-999"
    monkeypatch.setattr(
        orchestrator.CoupangPartnersClient, "fetch", lambda self, keyword="": [other_product]
    )
    orchestrator.collect_and_score(keyword="이어폰", top_n=20)

    with get_session() as session:
        assert session.query(Product).count() == 2
