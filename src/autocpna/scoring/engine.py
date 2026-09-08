"""상품 점수화 엔진.

가중합 방식: score = sum(weight_i * normalized_metric_i)
가중치는 config/scoring_weights.yaml 에서 관리.
"""
from __future__ import annotations

from dataclasses import dataclass

from autocpna.config import get_scoring_weights


@dataclass
class ScoreBreakdown:
    total: float
    components: dict[str, float]


class ScoringEngine:
    def __init__(self) -> None:
        cfg = get_scoring_weights()
        self.weights: dict[str, float] = cfg["weights"]
        self.default_conversion_rate: float = cfg.get("default_conversion_rate", 0.02)
        self.min_score_threshold: float = cfg.get("min_score_threshold", 0.0)

    def score(self, product: dict) -> ScoreBreakdown:
        """product dict는 아래 키를 (일부 누락 가능) 포함해야 함:
        search_volume, trend_momentum, margin_rate, conversion_rate, seasonality_fit
        모든 입력값은 0~1 범위로 정규화되어 있다고 가정 (정규화는 호출부 책임).
        """
        metrics = {
            "search_volume": product.get("search_volume", 0.0),
            "trend_momentum": product.get("trend_momentum", 0.0),
            "margin_rate": product.get("margin_rate", 0.0),
            "conversion_rate": product.get("conversion_rate") or self.default_conversion_rate,
            "seasonality_fit": product.get("seasonality_fit", 0.0),
        }
        components = {
            key: metrics[key] * self.weights.get(key, 0.0) for key in metrics
        }
        total = sum(components.values())
        return ScoreBreakdown(total=total, components=components)

    def rank(self, products: list[dict], top_n: int | None = None) -> list[tuple[dict, ScoreBreakdown]]:
        """점수 계산 후 임계값 필터링 + 내림차순 정렬."""
        scored = [(p, self.score(p)) for p in products]
        scored = [(p, s) for p, s in scored if s.total >= self.min_score_threshold]
        scored.sort(key=lambda pair: pair[1].total, reverse=True)
        return scored[:top_n] if top_n else scored
