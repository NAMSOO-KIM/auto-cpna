from __future__ import annotations

from autocpna.config import get_channels_config
from autocpna.content_gen.base import ChannelGenerator


class InstagramGenerator(ChannelGenerator):
    channel = "instagram"

    def build_user_prompt(self, product: dict) -> str:
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
            f"- 제휴 링크 고지 문구 포함"
        )
