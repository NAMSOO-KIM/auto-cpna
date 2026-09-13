from __future__ import annotations

from autocpna.content_gen.base import MODEL, ChannelGenerator


class BlogGenerator(ChannelGenerator):
    channel = "naver_blog"

    def build_user_prompt(self, product: dict, feedback: str = "") -> str:
        """비교 대상이 마땅치 않을 때 쓰는 단일 상품 리뷰용 프롬프트.
        기본 컨셉은 build_comparison_prompt (추천 TOP N / 비교형) 사용."""
        return (
            f"다음 상품으로 네이버 블로그용 정보성 리뷰 글을 작성해줘.\n"
            f"상품명: {product['name']}\n"
            f"카테고리: {product['category']}\n"
            f"가격: {product['price']}원\n"
            f"구매 링크: {product['product_url']}\n\n"
            f"요구사항:\n"
            f"- SEO를 고려한 소제목 구조 (H2/H3에 해당하는 텍스트 블록)\n"
            f"- 장점과 단점을 균형 있게, 최소 각 2개 이상\n"
            f"- 본문 하단에 구매 링크와 다음 제휴 고지 문구를 그대로 포함: "
            f"\"{self.disclosure_text(product)}\"\n"
            f"- 1200~1800자 분량"
            f"{self.feedback_block(feedback)}"
        )

    def build_comparison_prompt(self, topic: str, products: list[dict], feedback: str = "") -> str:
        """'OO 추천 TOP N' / 비교형 콘텐츠 프롬프트. naver_blog 기본 포맷.

        제휴 고지 문구는 첫 상품의 source를 기준으로 하나만 고른다 - 비교글은
        보통 같은 제휴 프로그램의 상품끼리 묶이므로, 프로그램이 실제로 섞여
        있다면 상품별로 별도 고지가 필요하니 이 함수를 그대로 쓰지 말 것.
        """
        items = "\n".join(
            f"{i}. {p['name']} - {p['price']}원 (카테고리: {p['category']}, 링크: {p['product_url']})"
            for i, p in enumerate(products, start=1)
        )
        disclosure = self.disclosure_text(products[0])
        return (
            f"'{topic} 추천 TOP {len(products)}' 형식의 네이버 블로그 비교 글을 작성해줘.\n\n"
            f"비교 대상 상품:\n{items}\n\n"
            f"요구사항:\n"
            f"- 도입부에서 독자가 '{topic}'을(를) 찾게 된 상황과 고민을 짚어준다\n"
            f"- 상품마다 소제목을 나누고, 각 상품에 장점 / 단점 / 이런 분께 추천 을 명시\n"
            f"- 가격·핵심 특징을 한눈에 비교하는 마크다운 표 포함 "
            f"(| 상품명 | 가격 | 장점 | 이런 분께 |)\n"
            f"- 순위를 매기되 '정답은 없고 상황에 따라 다르다'는 균형 잡힌 결론\n"
            f"- 상품 소개마다 구매 링크 삽입, 본문 상단에 다음 제휴 고지 문구를 그대로 포함: "
            f"\"{disclosure}\"\n"
            f"- 1500~2200자 분량"
            f"{self.feedback_block(feedback)}"
        )

    def generate_comparison(self, topic: str, products: list[dict], feedback: str = "") -> str:
        message = self._client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=self._build_system_prompt(),
            messages=[
                {
                    "role": "user",
                    "content": self.build_comparison_prompt(topic, products, feedback),
                }
            ],
        )
        return message.content[0].text
