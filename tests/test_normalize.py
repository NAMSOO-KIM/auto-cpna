from autocpna.scoring.normalize import normalize_search_volume, normalize_trend_momentum


def test_normalize_search_volume_clips_to_0_1():
    assert normalize_search_volume(50) == 0.5
    assert normalize_search_volume(150) == 1.0
    assert normalize_search_volume(-10) == 0.0


def test_normalize_trend_momentum_maps_zero_change_to_midpoint():
    # 변화 없음(momentum=0) -> 정규화 구간 [-1, 2]의 1/3 지점
    assert round(normalize_trend_momentum(0.0), 4) == round(1 / 3, 4)


def test_normalize_trend_momentum_clips_extremes():
    assert normalize_trend_momentum(-5.0) == 0.0  # -100% 이하로 클리핑
    assert normalize_trend_momentum(10.0) == 1.0  # +200% 이상으로 클리핑
