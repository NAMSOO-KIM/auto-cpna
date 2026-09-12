from autocpna.scoring.normalize import compute_seasonality_fit


def test_peak_month_scores_one():
    # 12월이 매년 가장 높은 달 -> 1.0
    ratios = {
        "2024-11": 30.0,
        "2024-12": 90.0,
        "2025-01": 20.0,
        "2025-11": 35.0,
        "2025-12": 100.0,
    }
    assert compute_seasonality_fit(ratios, reference_month=12) == 1.0


def test_off_season_month_scores_below_one():
    ratios = {
        "2024-11": 30.0,
        "2024-12": 90.0,
        "2025-11": 35.0,
        "2025-12": 100.0,
    }
    score = compute_seasonality_fit(ratios, reference_month=11)
    assert 0.0 < score < 1.0
    assert score == (30.0 + 35.0) / 2 / ((90.0 + 100.0) / 2)


def test_insufficient_data_returns_zero():
    assert compute_seasonality_fit({"2025-12": 100.0}, reference_month=12) == 0.0
    assert compute_seasonality_fit({}, reference_month=12) == 0.0


def test_month_with_no_history_returns_zero():
    ratios = {"2024-12": 90.0, "2025-01": 20.0}
    assert compute_seasonality_fit(ratios, reference_month=6) == 0.0
