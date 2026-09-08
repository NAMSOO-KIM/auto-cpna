from __future__ import annotations

from autocpna.content_gen.base import ChannelGenerator


class BlogGenerator(ChannelGenerator):
    channel = "naver_blog"

    def build_user_prompt(self, product: dict) -> str:
        return (
            f"다음 상품으로 네이버 블로그용 정보성 리뷰 글을 작성해줘.\n"
            f"상품명: {product['name']}\n"
            f"카테고리: {product['category']}\n"
            f"가격: {product['price']}원\n"
            f"구매 링크: {product['product_url']}\n\n"
            f"요구사항:\n"
            f"- SEO를 고려한 소제목 구조 (H2/H3에 해당하는 텍스트 블록)\n"
            f"- 장점과 단점을 균형 있게, 최소 각 2개 이상\n"
            f"- 본문 하단에 구매 링크와 제휴 고지 문구\n"
            f"- 1200~1800자 분량"
        )
