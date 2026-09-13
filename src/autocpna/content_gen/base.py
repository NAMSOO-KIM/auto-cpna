"""채널별 콘텐츠 생성기 공통 베이스."""
from __future__ import annotations

from abc import ABC, abstractmethod

import anthropic

from autocpna.config import get_personas_config, get_settings

MODEL = "claude-sonnet-4-5"

# 제휴 프로그램별 실제 고지 문구. product["source"]로 어떤 프로그램인지 구분해
# 골라 쓴다 - 예를 들어 네이버 쇼핑커넥트 상품에 "#쿠팡파트너스"라고 잘못
# 고지하면 실제 제휴 관계와 다른 표시가 되어버린다.
DISCLOSURE_TEXT: dict[str, str] = {
    "coupang_partners": "이 포스팅은 쿠팡파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.",
    "naver_shopping_connect": "이 포스팅은 네이버 쇼핑커넥트를 통해 일정액의 수수료를 제공받을 수 있습니다.",
}
DEFAULT_SOURCE = "coupang_partners"


class ChannelGenerator(ABC):
    channel: str  # instagram / threads / naver_blog

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
        personas = get_personas_config()
        self.persona_cfg = personas[self.channel]
        self.common_rules: list[str] = personas.get("common_rules", [])

    def disclosure_text(self, product: dict) -> str:
        """product["source"]에 맞는 제휴 고지 문구. 모르는 source는 쿠팡파트너스 문구로 대체."""
        return DISCLOSURE_TEXT.get(product.get("source", DEFAULT_SOURCE), DISCLOSURE_TEXT[DEFAULT_SOURCE])

    def feedback_block(self, feedback: str) -> str:
        """검수자가 반려하며 남긴 코멘트를 재생성 프롬프트에 끼워 넣을 때 쓰는 공통 문구.
        feedback이 비어 있으면(최초 생성) 빈 문자열을 반환해 프롬프트에 영향이 없다."""
        if not feedback:
            return ""
        return f"\n\n[이전 검수 반려 사유 - 이번에는 반드시 반영해서 다시 작성]: {feedback}"

    def _build_system_prompt(self) -> str:
        rules = "\n".join(f"- {r}" for r in self.common_rules)
        return (
            f"당신은 {self.persona_cfg['persona']} 역할을 맡은 콘텐츠 작성자입니다.\n"
            f"톤: {self.persona_cfg['tone']}\n"
            f"유도 방식: {self.persona_cfg['cta']}\n\n"
            f"반드시 지켜야 할 규칙:\n{rules}"
        )

    @abstractmethod
    def build_user_prompt(self, product: dict, feedback: str = "") -> str:
        """product dict(name, category, price, product_url 등)를 받아
        채널에 맞는 사용자 프롬프트를 구성. feedback이 있으면(재생성 요청)
        feedback_block()으로 프롬프트 끝에 반영해야 한다."""
        raise NotImplementedError

    def generate(self, product: dict, feedback: str = "") -> str:
        message = self._client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=self._build_system_prompt(),
            messages=[{"role": "user", "content": self.build_user_prompt(product, feedback)}],
        )
        return message.content[0].text
