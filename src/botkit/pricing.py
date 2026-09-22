"""단가는 YAML에서 읽는다. 모르는 모델을 0원으로 기록하면 마진을 오판한다."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import Field, ValidationError

from botkit.jobspec import Strict


class PricingError(RuntimeError):
    pass


class ModelPrice(Strict):
    input_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    output_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)

    def estimate(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            self.input_usd_per_million * input_tokens
            + self.output_usd_per_million * output_tokens
        ) / Decimal(1_000_000)


class PriceTable(Strict):
    source: str
    checked_on: str
    models: dict[str, ModelPrice] = Field(min_length=1)


def load_price(path: str | Path, model: str) -> ModelPrice:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        table = PriceTable.model_validate(data)
    except (OSError, ValueError, yaml.YAMLError, ValidationError) as exc:
        # YAML 원문에는 잘못 붙여넣은 시크릿도 있을 수 있어 검증 예외를 출력하지 않는다.
        raise PricingError("단가표를 읽을 수 없습니다. history.pricing_file과 단가를 확인하세요.") from exc
    if model not in table.models:
        raise PricingError("사용 모델의 단가가 없습니다. config/pricing.yaml에 모델을 등록하세요.")
    return table.models[model]
