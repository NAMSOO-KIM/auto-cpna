from autocpna.scoring.engine import ScoringEngine


def test_score_uses_default_conversion_rate_when_missing():
    engine = ScoringEngine()
    product = {
        "search_volume": 0.5,
        "trend_momentum": 0.3,
        "margin_rate": 0.2,
        "seasonality_fit": 0.1,
        # conversion_rate 누락 -> default_conversion_rate 사용
    }
    breakdown = engine.score(product)
    assert breakdown.total > 0
    assert "conversion_rate" in breakdown.components


def test_rank_filters_below_threshold_and_sorts_desc():
    engine = ScoringEngine()
    engine.min_score_threshold = 0.1
    high = {"search_volume": 1.0, "trend_momentum": 1.0, "margin_rate": 1.0,
            "conversion_rate": 1.0, "seasonality_fit": 1.0}
    low = {"search_volume": 0.0, "trend_momentum": 0.0, "margin_rate": 0.0,
           "conversion_rate": 0.0, "seasonality_fit": 0.0}

    ranked = engine.rank([low, high])
    assert len(ranked) == 1
    assert ranked[0][0] is high
