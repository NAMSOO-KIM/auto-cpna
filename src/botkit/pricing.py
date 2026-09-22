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
    except ValidationError as exc:
        # 값이 아니라 '어느 키가 왜 틀렸는지'만 보여준다. 이 파일은 커밋되는
        # 공개 단가표라 시크릿이 들어갈 자리가 없지만, 원문을 그대로 쏟아내는
        # 습관은 다른 YAML을 지정했을 때 사고가 된다.
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(최상위)'}: {err['msg']}"
            for err in exc.errors()
        )
        raise PricingError(f"단가표 형식이 잘못되었습니다 ({path}) - {details}") from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise PricingError(
            f"단가표를 읽을 수 없습니다 ({path}): {type(exc).__name__}. "
            "history.pricing_file 경로를 확인하세요."
        ) from exc
    if model not in table.models:
        raise PricingError(
            f"모델 '{model}'의 단가가 {path}에 없습니다. "
            f"등록된 모델: {sorted(table.models)}"
        )
    return table.models[model]
