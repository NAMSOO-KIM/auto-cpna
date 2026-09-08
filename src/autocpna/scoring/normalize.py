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
