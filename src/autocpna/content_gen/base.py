"""채널별 콘텐츠 생성기 공통 베이스."""
from __future__ import annotations

from abc import ABC, abstractmethod

import anthropic

from autocpna.config import get_personas_config, get_settings

MODEL = "claude-sonnet-4-5"


class ChannelGenerator(ABC):
    channel: str  # instagram / threads / naver_blog

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
        personas = get_personas_config()
        self.persona_cfg = personas[self.channel]
        self.common_rules: list[str] = personas.get("common_rules", [])

    def _build_system_prompt(self) -> str:
        rules = "\n".join(f"- {r}" for r in self.common_rules)
        return (
            f"당신은 {self.persona_cfg['persona']} 역할을 맡은 콘텐츠 작성자입니다.\n"
            f"톤: {self.persona_cfg['tone']}\n"
            f"유도 방식: {self.persona_cfg['cta']}\n\n"
            f"반드시 지켜야 할 규칙:\n{rules}"
        )

    @abstractmethod
    def build_user_prompt(self, product: dict) -> str:
        """product dict(name, category, price, product_url 등)를 받아
        채널에 맞는 사용자 프롬프트를 구성."""
        raise NotImplementedError

    def generate(self, product: dict) -> str:
        message = self._client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=self._build_system_prompt(),
            messages=[{"role": "user", "content": self.build_user_prompt(product)}],
        )
        return message.content[0].text
