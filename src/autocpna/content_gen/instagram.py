from __future__ import annotations

from autocpna.config import get_channels_config
from autocpna.content_gen.base import ChannelGenerator


class InstagramGenerator(ChannelGenerator):
    channel = "instagram"

    def build_user_prompt(self, product: dict, feedback: str = "") -> str:
        max_tags = get_channels_config()["instagram"]["max_hashtags"]
        return (
            f"다음 상품으로 인스타그램 피드 캡션을 작성해줘.\n"
            f"상품명: {product['name']}\n"
            f"카테고리: {product['category']}\n"
            f"가격: {product['price']}원\n"
            f"구매 링크: {product['product_url']}\n\n"
            f"요구사항:\n"
            f"- 3~5문장의 짧은 감성 캡션\n"
            f"- 해시태그는 최대 {max_tags}개, 캡션 아래 별도 줄에\n"
            f"- 다음 제휴 고지 문구를 캡션 하단에 그대로 포함: \"{self.disclosure_text(product)}\""
            f"{self.feedback_block(feedback)}"
        )

    def build_image_prompt(self, product: dict) -> str:
        """이미지 생성기(예: OpenAIImageGenerator)에 넘길 비주얼 프롬프트."""
        return (
            f"{product['name']}({product['category']})을 자연스럽게 사용하는 "
            f"라이프스타일 사진. 감성적이고 트렌디한 무드, 파스텔 톤 or 내추럴한 조명, "
            f"미니멀한 배경, 인스타그램 피드에 어울리는 세로형(4:5) 구도. 텍스트나 로고는 넣지 않음."
        )
