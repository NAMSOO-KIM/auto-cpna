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
from autocpna.ingestion.naver_datalab import NaverDatalabClient
from autocpna.models.content_draft import ContentDraft, ReviewStatus
from autocpna.models.product import Product
from autocpna.publish.base import Publisher
from autocpna.publish.instagram_publisher import InstagramPublisher
from autocpna.publish.naver_blog_publisher import NaverBlogPublisher
from autocpna.publish.threads_publisher import ThreadsPublisher
from autocpna.scoring.engine import ScoringEngine
from autocpna.scoring.normalize import normalize_search_volume, normalize_trend_momentum

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
    """상품 수집(쿠팡파트너스) + 검색 트렌드(네이버 데이터랩) 병합 -> 점수화 -> DB 저장.

    네이버 데이터랩은 상품 단위가 아니라 키워드 단위 트렌드만 제공하므로,
    같은 keyword로 조회된 상품들은 동일한 search_volume/trend_momentum을 공유한다.
    conversion_rate(자체 클릭 로그 필요)와 seasonality_fit(계절성 데이터 필요)은
    아직 연결된 데이터 소스가 없어 0.0으로 남겨두고, 점수화 시 conversion_rate만
    ScoringEngine의 카테고리 기본값으로 대체된다.
    """
    raw_products = CoupangPartnersClient().fetch(keyword=keyword)

    search_volume = 0.0
    trend_momentum = 0.0
    if keyword:
        trend_results = NaverDatalabClient().fetch(keywords=[keyword])
        if trend_results:
            search_volume = normalize_search_volume(trend_results[0]["search_volume"])
            trend_momentum = normalize_trend_momentum(trend_results[0]["trend_momentum"])

    for product in raw_products:
        product["search_volume"] = search_volume
        product["trend_momentum"] = trend_momentum

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
                search_volume=data.get("search_volume", 0.0),
                trend_momentum=data.get("trend_momentum", 0.0),
                conversion_rate=data.get("conversion_rate", 0.0),
                seasonality_fit=data.get("seasonality_fit", 0.0),
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


def generate_blog_comparison_draft(topic: str, products: list[Product]) -> ContentDraft:
    """네이버 블로그용 'OO 추천 TOP N' 비교 콘텐츠 초안 생성.

    ContentDraft.product_id는 단일 FK라 여러 상품을 모두 연결할 수 없으므로,
    검수 시 참고용으로 대표 상품(첫 번째, 보통 최고 점수)에만 연결한다.
    나머지 상품 정보는 caption_or_body 본문 안에 이미 포함되어 있다.
    """
    if not products:
        raise ValueError("products가 비어 있습니다")

    generator = BlogGenerator()
    product_dicts = [
        {
            "name": p.name,
            "category": p.category,
            "price": p.price,
            "product_url": p.product_url,
        }
        for p in products
    ]
    text = generator.generate_comparison(topic, product_dicts)

    with get_session() as session:
        draft = ContentDraft(
            product_id=products[0].id,
            channel="naver_blog",
            caption_or_body=text,
            status=ReviewStatus.PENDING,
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
    return draft


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
