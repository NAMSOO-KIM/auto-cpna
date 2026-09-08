"""전체 파이프라인 오케스트레이션.

collect_and_score -> generate_drafts -> (사람 검수) -> publish_approved
각 단계는 독립적으로도 CLI에서 호출 가능하도록 함수 단위로 분리.
"""
from __future__ import annotations

from autocpna.config import get_channels_config
from autocpna.content_gen.blog import BlogGenerator
from autocpna.content_gen.instagram import InstagramGenerator
from autocpna.content_gen.threads import ThreadsGenerator
from autocpna.db import get_session
from autocpna.ingestion.coupang_partners import CoupangPartnersClient
from autocpna.models.content_draft import ContentDraft, ReviewStatus
from autocpna.models.product import Product
from autocpna.publish.base import Publisher
from autocpna.publish.instagram_publisher import InstagramPublisher
from autocpna.publish.naver_blog_publisher import NaverBlogPublisher
from autocpna.publish.threads_publisher import ThreadsPublisher
from autocpna.scoring.engine import ScoringEngine

GENERATORS = {
    "instagram": InstagramGenerator,
    "threads": ThreadsGenerator,
    "naver_blog": BlogGenerator,
}

PUBLISHERS: dict[str, Publisher] = {
    "instagram": InstagramPublisher,
    "threads": ThreadsPublisher,
    "naver_blog": NaverBlogPublisher,
}


def collect_and_score(keyword: str = "", top_n: int = 20) -> list[Product]:
    """상품 수집 -> 점수화 -> DB 저장, 상위 top_n 반환."""
    raw_products = CoupangPartnersClient().fetch(keyword=keyword)
    engine = ScoringEngine()
    ranked = engine.rank(raw_products, top_n=top_n)

    saved: list[Product] = []
    with get_session() as session:
        for data, breakdown in ranked:
            product = Product(
                external_id=data["external_id"],
                name=data["name"],
                category=data["category"],
                price=data["price"],
                margin_rate=data.get("margin_rate", 0.0),
                product_url=data.get("product_url", ""),
                image_url=data.get("image_url", ""),
                score=breakdown.total,
            )
            session.add(product)
            saved.append(product)
        session.commit()
        for p in saved:
            session.refresh(p)
    return saved


def generate_drafts(product: Product, channels: list[str] | None = None) -> list[ContentDraft]:
    """상품 하나에 대해 채널별 콘텐츠 초안을 생성하고 검수 대기열에 넣는다."""
    channels_cfg = get_channels_config()
    channels = channels or [c for c, cfg in channels_cfg.items() if cfg.get("enabled")]

    product_dict = {
        "name": product.name,
        "category": product.category,
        "price": product.price,
        "product_url": product.product_url,
    }

    drafts: list[ContentDraft] = []
    with get_session() as session:
        for channel in channels:
            generator = GENERATORS[channel]()
            text = generator.generate(product_dict)
            draft = ContentDraft(
                product_id=product.id,
                channel=channel,
                caption_or_body=text,
                status=ReviewStatus.PENDING,
            )
            session.add(draft)
            drafts.append(draft)
        session.commit()
        for d in drafts:
            session.refresh(d)
    return drafts


def publish_approved_draft(draft_id: int) -> None:
    """승인된 초안을 발행한다.

    채널별 발행 가능 여부(자동 발행 vs 수동 발행 전용)는 각 Publisher 구현체
    내부에서 강제된다 (예: NaverBlogPublisher는 절대 자동 발행하지 않고
    항상 실패 결과 + 로컬 초안 파일을 반환).
    """
    with get_session() as session:
        draft = session.get(ContentDraft, draft_id)
        if draft is None:
            raise ValueError(f"draft {draft_id} not found")
        if draft.status != ReviewStatus.APPROVED:
            raise ValueError(f"draft {draft_id} is not approved (status={draft.status})")

        publisher = PUBLISHERS[draft.channel]()
        result = publisher.publish(draft)

        if result.success:
            draft.status = ReviewStatus.PUBLISHED
        session.commit()
