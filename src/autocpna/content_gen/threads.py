from __future__ import annotations

from autocpna.content_gen.base import ChannelGenerator


class ThreadsGenerator(ChannelGenerator):
    channel = "threads"

    def build_user_prompt(self, product: dict) -> str:
        return (
            f"다음 상품에 대해 스레드(Threads) 게시글을 작성해줘.\n"
            f"상품명: {product['name']}\n"
            f"카테고리: {product['category']}\n"
            f"가격: {product['price']}원\n"
            f"구매 링크: {product['product_url']}\n\n"
            f"요구사항:\n"
            f"- 일상 속 고민에서 시작해 자연스럽게 상품으로 이어지는 스토리텔링\n"
            f"- 500자 이내\n"
            f"- 마지막에 댓글을 유도하는 질문 1개\n"
            f"- 다음 제휴 고지 문구를 그대로 포함: \"{self.disclosure_text(product)}\""
        )
