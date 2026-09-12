"""ScoringEngine에 넣기 전, 수집 단계의 원시 지표를 0~1 범위로 정규화.

ScoringEngine.score()는 입력이 이미 0~1로 정규화되어 있다고 가정하므로
(engine.py 참고), 원시 데이터를 다루는 모든 ingestion 결과는 여기를 거쳐야 함.
"""
from __future__ import annotations


def normalize_search_volume(raw_ratio: float) -> float:
    """네이버 데이터랩 검색어 트렌드는 0~100 사이 상대 지수로 반환된다."""
    return max(0.0, min(raw_ratio / 100.0, 1.0))


def normalize_trend_momentum(raw_momentum: float) -> float:
    """(최근-과거)/과거 형태의 증감률.

    -100%(수요 소멸) ~ +200%(3배 급증) 구간으로 클리핑한 뒤 0~1로 스케일.
    구간 밖 극단값(예: 과거 검색량이 0에 가까워 momentum이 폭발하는 경우)은
    클리핑으로 완충한다.
    """
    clipped = max(-1.0, min(raw_momentum, 2.0))
    return (clipped + 1.0) / 3.0


def compute_seasonality_fit(monthly_ratios: dict[str, float], reference_month: int) -> float:
    """월별 검색 트렌드 시계열로 "이 달이 계절적 성수기인가"를 0~1로 계산.

    monthly_ratios: {"YYYY-MM": ratio, ...} 형태의 데이터랩 월별 상대 지수
    (최소 2개 서로 다른 월 필요, 이상적으로는 12개월 이상).
    reference_month: 1~12, 평가하려는 달(보통 현재 달 또는 발행 예정 달).

    같은 달(예: 매년 12월)의 평균 ratio를, 전체 달 중 평균 ratio가 가장 높은
    달 대비 비율로 반환한다 (1.0 = 역대 최고 성수기 달, 0.0 = 데이터 없음/무의미).
    trend_momentum(최근 며칠~몇 주의 단기 변화)과 달리 연중 반복되는 계절
    패턴을 포착하기 위한 지표다.
    """
    by_month: dict[int, list[float]] = {}
    for period, ratio in monthly_ratios.items():
        month = int(period.split("-")[1])
        by_month.setdefault(month, []).append(ratio)

    if len(by_month) < 2:
        return 0.0

    averages = {month: sum(ratios) / len(ratios) for month, ratios in by_month.items()}
    max_average = max(averages.values())
    if max_average <= 0:
        return 0.0
    return averages.get(reference_month, 0.0) / max_average
