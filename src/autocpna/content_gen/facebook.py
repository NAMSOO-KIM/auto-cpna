from __future__ import annotations

from autocpna.content_gen.base import ChannelGenerator


class FacebookGenerator(ChannelGenerator):
    channel = "facebook"

    def build_user_prompt(self, product: dict) -> str:
        return (
            f"다음 상품으로 Facebook 페이지 게시글을 작성해줘.\n"
            f"상품명: {product['name']}\n"
            f"카테고리: {product['category']}\n"
            f"가격: {product['price']}원\n"
            f"구매 링크: {product['product_url']}\n\n"
            f"요구사항:\n"
            f"- 감성적 수식어보다 가격/특징/활용법 같은 실용 정보 위주로 3~6문장\n"
            f"- 존댓말, 이웃에게 소개하듯 친근하지만 정중한 어투\n"
            f"- 본문 마지막에 링크를 별도 줄로 배치\n"
            f"- 다음 제휴 고지 문구를 그대로 포함: \"{self.disclosure_text(product)}\""
        )
