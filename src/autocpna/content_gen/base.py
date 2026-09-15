"""채널별 콘텐츠 생성기 공통 베이스."""
from __future__ import annotations

from abc import ABC, abstractmethod

import anthropic

from autocpna.config import get_personas_config, get_settings

MODEL = "claude-opus-5"

# 네이버 블로그 프롬프트는 1200~2200자 분량을 요구하는데, 한국어는 토큰당
# 글자 수가 영어보다 훨씬 적어서(대략 글자수의 1~1.5배가 토큰수) 1024~2048
# 토큰으로는 본문이 중간에 잘린다. 잘리면 프롬프트가 "본문 하단에" 넣으라고
# 지시한 제휴 고지 문구가 통째로 사라져서, 고지 없는 초안이 검수 큐에 올라간다.
# 출력 토큰은 실제 생성량만 과금되므로 상한을 넉넉히 둬도 비용은 늘지 않는다.
MAX_TOKENS = 16000

# 제휴 프로그램별 실제 고지 문구. product["source"]로 어떤 프로그램인지 구분해
# 골라 쓴다 - 예를 들어 네이버 쇼핑커넥트 상품에 "#쿠팡파트너스"라고 잘못
# 고지하면 실제 제휴 관계와 다른 표시가 되어버린다.
DISCLOSURE_TEXT: dict[str, str] = {
    "coupang_partners": "이 포스팅은 쿠팡파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.",
    "naver_shopping_connect": "이 포스팅은 네이버 쇼핑커넥트를 통해 일정액의 수수료를 제공받을 수 있습니다.",
}
DEFAULT_SOURCE = "coupang_partners"


def extract_text(message) -> str:
    """응답에서 text 블록만 모아 반환.

    content[0]이 text 블록이라고 가정할 수 없다 - adaptive thinking이 기본으로
    켜진 모델은 thinking 블록을 먼저 내보내고, 그 블록에는 .text 자체가 없어서
    content[0].text가 AttributeError로 터진다.

    stop_reason이 max_tokens면 본문이 중간에 잘린 것이다. 잘린 초안은 제휴 고지
    문구가 빠져 있을 수 있어 그대로 검수 큐에 넣으면 안 되므로 명시적으로 막는다.
    """
    if message.stop_reason == "max_tokens":
        raise RuntimeError(
            f"생성 본문이 max_tokens({MAX_TOKENS})에서 잘렸습니다. 제휴 고지 문구가 "
            "누락됐을 수 있어 초안으로 쓰지 않습니다. 프롬프트의 분량 요구를 줄이거나 "
            "MAX_TOKENS를 올리세요."
        )
    texts = [block.text for block in message.content if block.type == "text"]
    if not texts:
        raise RuntimeError(f"응답에 text 블록이 없습니다 (stop_reason={message.stop_reason})")
    return "".join(texts)


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

    def complete(self, user_prompt: str) -> str:
        """user_prompt로 본문을 생성한다. generate/generate_comparison 공용 경로."""
        message = self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=self._build_system_prompt(),
            messages=[{"role": "user", "content": user_prompt}],
        )
        return extract_text(message)

    def generate(self, product: dict, feedback: str = "") -> str:
        return self.complete(self.build_user_prompt(product, feedback))
