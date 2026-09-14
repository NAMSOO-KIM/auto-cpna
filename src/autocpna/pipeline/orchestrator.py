"""전체 파이프라인 오케스트레이션.

collect_and_score -> generate_drafts -> (사람 검수) -> publish_approved
각 단계는 독립적으로도 CLI에서 호출 가능하도록 함수 단위로 분리.
"""
from __future__ import annotations

import datetime as dt
import uuid

import httpx

from autocpna.config import get_channels_config
from autocpna.content_gen.blog import BlogGenerator
from autocpna.content_gen.facebook import FacebookGenerator
from autocpna.content_gen.instagram import InstagramGenerator
from autocpna.content_gen.threads import ThreadsGenerator
from autocpna.db import get_session
from autocpna.ingestion.coupang_partners import CoupangPartnersClient
from autocpna.ingestion.coupang_reports import CoupangReportsClient
from autocpna.ingestion.naver_datalab import NaverDatalabClient
from autocpna.media_gen.cloudinary_uploader import CloudinaryUploader
from autocpna.media_gen.image_generator import CHANNEL_IMAGE_SPECS
from autocpna.media_gen.openai_image_generator import OpenAIImageGenerator
from autocpna.models.content_draft import ContentDraft, ReviewStatus
from autocpna.models.product import Product
from autocpna.models.publish_log import PublishLog
from autocpna.publish.base import Publisher, PublishResult
from autocpna.publish.facebook_publisher import FacebookPublisher
from autocpna.publish.instagram_publisher import InstagramPublisher
from autocpna.publish.naver_blog_publisher import NaverBlogPublisher
from autocpna.publish.threads_publisher import ThreadsPublisher
from autocpna.scoring.engine import ScoringEngine
from autocpna.scoring.normalize import (
    compute_seasonality_fit,
    normalize_search_volume,
    normalize_trend_momentum,
)

CONVERSION_RATE_LOOKBACK_DAYS = 30

GENERATORS = {
    "instagram": InstagramGenerator,
    "threads": ThreadsGenerator,
    "naver_blog": BlogGenerator,
    "facebook": FacebookGenerator,
}

PUBLISHERS: dict[str, Publisher] = {
    "instagram": InstagramPublisher,
    "threads": ThreadsPublisher,
    "naver_blog": NaverBlogPublisher,
    "facebook": FacebookPublisher,
}


def _fetch_seasonality_fit(keyword: str, reference_month: int | None = None) -> float:
    """데이터랩 월별 시계열로 계절성 점수를 계산. 키워드가 없거나 API 호출이
    실패하면(신규 키워드라 히스토리가 없는 경우 포함) 0.0으로 안전하게 폴백."""
    if not keyword:
        return 0.0
    try:
        monthly_series = NaverDatalabClient().fetch_monthly_series(keyword)
    except httpx.HTTPError:
        return 0.0
    reference_month = reference_month or dt.date.today().month
    return compute_seasonality_fit(monthly_series, reference_month=reference_month)


def _fetch_account_conversion_rate() -> float | None:
    """쿠팡파트너스 커미션 리포트로 계정 전체 실측 전환율을 계산.

    상품/카테고리 단위 실측치가 아니라 계정 전체 평균이지만, 스코어링
    엔진의 config 고정값(default_conversion_rate)보다는 실데이터에 가깝다.
    리포트 API 호출이 실패하면(권한 미부여, 신규 계정 등) None을 반환해
    ScoringEngine이 기존처럼 config 기본값을 쓰도록 둔다.
    """
    end = dt.date.today()
    start = end - dt.timedelta(days=CONVERSION_RATE_LOOKBACK_DAYS)
    try:
        return CoupangReportsClient().conversion_rate(
            start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        )
    except (httpx.HTTPError, RuntimeError):
        return None


def collect_and_score(keyword: str = "", top_n: int = 20) -> list[Product]:
    """상품 수집(쿠팡파트너스) + 검색 트렌드(네이버 데이터랩) 병합 -> 점수화 -> DB 저장.

    네이버 데이터랩은 상품 단위가 아니라 키워드 단위 트렌드만 제공하므로,
    같은 keyword로 조회된 상품들은 동일한 search_volume/trend_momentum/
    seasonality_fit을 공유한다. conversion_rate는 상품/카테고리 단위 실데이터가
    없어 쿠팡파트너스 커미션 리포트로 계산한 계정 전체 실측 평균을 쓰고,
    리포트를 가져올 수 없을 때만(신규 계정 등) ScoringEngine의 config
    기본값(default_conversion_rate)으로 대체된다.
    """
    raw_products = CoupangPartnersClient().fetch(keyword=keyword)

    search_volume = 0.0
    trend_momentum = 0.0
    if keyword:
        trend_results = NaverDatalabClient().fetch(keywords=[keyword])
        if trend_results:
            search_volume = normalize_search_volume(trend_results[0]["search_volume"])
            trend_momentum = normalize_trend_momentum(trend_results[0]["trend_momentum"])

    seasonality_fit = _fetch_seasonality_fit(keyword)
    conversion_rate = _fetch_account_conversion_rate()

    for product in raw_products:
        product["search_volume"] = search_volume
        product["trend_momentum"] = trend_momentum
        product["seasonality_fit"] = seasonality_fit
        if conversion_rate is not None:
            product["conversion_rate"] = conversion_rate

    engine = ScoringEngine()
    ranked = engine.rank(raw_products, top_n=top_n)

    saved: list[Product] = []
    with get_session() as session:
        external_ids = [data["external_id"] for data, _ in ranked]
        existing_by_external_id = {
            p.external_id: p
            for p in session.query(Product).filter(Product.external_id.in_(external_ids)).all()
        }
        for data, breakdown in ranked:
            product = existing_by_external_id.get(data["external_id"])
            if product is None:
                product = Product(external_id=data["external_id"])
                session.add(product)
            product.source = data.get("source", "coupang_partners")
            product.name = data["name"]
            product.category = data["category"]
            product.price = data["price"]
            product.margin_rate = data.get("margin_rate", 0.0)
            product.search_volume = data.get("search_volume", 0.0)
            product.trend_momentum = data.get("trend_momentum", 0.0)
            product.conversion_rate = data.get("conversion_rate", 0.0)
            product.seasonality_fit = data.get("seasonality_fit", 0.0)
            product.product_url = data.get("product_url", "")
            product.image_url = data.get("image_url", "")
            product.score = breakdown.total
            saved.append(product)
        session.commit()
        for p in saved:
            session.refresh(p)
    return saved


def register_manual_product(
    *,
    name: str,
    category: str,
    price: float,
    product_url: str,
    margin_rate: float,
    source: str,
    keyword: str = "",
) -> Product:
    """공개 수집 API가 없는 제휴 프로그램(예: 네이버 쇼핑커넥트)의 상품을
    사람이 직접 등록한다.

    네이버 쇼핑커넥트는 크리에이터가 대상 상품을 골라 전용 링크를 발급받는
    구조이고 프로그램 자체에 조회/링크발급 API가 없어(2026-09 기준) 쿠팡
    파트너스처럼 자동 수집할 수 없다. product_url/margin_rate는 그렇게
    사람이 쇼핑커넥트 화면에서 직접 확인한 값을 그대로 입력받는다.

    keyword를 주면 데이터랩으로 search_volume/trend_momentum/seasonality_fit을
    collect_and_score와 동일한 방식으로 계산하고, 안 주면 0.0으로 둔다
    (conversion_rate는 프로그램별 클릭 데이터가 없어 항상 ScoringEngine의
    config 기본값으로 대체됨). 사람이 이미 골라서 등록하는 상품이므로
    collect_and_score와 달리 min_score_threshold 필터링은 적용하지 않는다.
    """
    search_volume = 0.0
    trend_momentum = 0.0
    if keyword:
        trend_results = NaverDatalabClient().fetch(keywords=[keyword])
        if trend_results:
            search_volume = normalize_search_volume(trend_results[0]["search_volume"])
            trend_momentum = normalize_trend_momentum(trend_results[0]["trend_momentum"])
    seasonality_fit = _fetch_seasonality_fit(keyword)

    breakdown = ScoringEngine().score(
        {
            "search_volume": search_volume,
            "trend_momentum": trend_momentum,
            "margin_rate": margin_rate,
            "seasonality_fit": seasonality_fit,
        }
    )

    with get_session() as session:
        product = Product(
            external_id=f"{source}:{uuid.uuid4().hex}",
            source=source,
            name=name,
            category=category,
            price=price,
            margin_rate=margin_rate,
            search_volume=search_volume,
            trend_momentum=trend_momentum,
            seasonality_fit=seasonality_fit,
            product_url=product_url,
            score=breakdown.total,
        )
        session.add(product)
        session.commit()
        session.refresh(product)
    return product


def _host_image_publicly(local_path: str) -> str:
    """Instagram 발행에 필요한 공개 URL을 얻기 위해 Cloudinary에 업로드.

    Cloudinary가 설정되어 있지 않거나 업로드가 실패하면(네트워크 오류 등)
    로컬 경로를 그대로 반환한다 - 이 경우 검수 화면에는 여전히 이미지가
    보이지만, InstagramPublisher가 발행 시점에 "공개 URL 아님" 오류로
    명확하게 막아준다(publish/instagram_publisher.py 참고).
    """
    uploader = CloudinaryUploader()
    if not uploader.configured:
        return local_path
    try:
        return uploader.upload(local_path)
    except httpx.HTTPError:
        return local_path


def _product_to_dict(product: Product) -> dict:
    return {
        "name": product.name,
        "category": product.category,
        "price": product.price,
        "product_url": product.product_url,
        "source": product.source,
    }


def _generate_channel_content(product: Product, channel: str, feedback: str = "") -> tuple[str, str]:
    """채널 하나에 대해 (본문, image_path)를 생성. instagram이 아니면 image_path는 "".

    feedback을 주면(반려 후 재생성) 생성기 프롬프트에 반영된다 - generate_drafts와
    regenerate_draft가 이 함수를 공유해서 최초 생성/재생성 로직이 갈라지지 않게 한다.
    """
    generator = GENERATORS[channel]()
    product_dict = _product_to_dict(product)
    text = generator.generate(product_dict, feedback=feedback)
    image_path = ""
    if channel == "instagram":
        image_prompt = generator.build_image_prompt(product_dict)
        local_image_path = OpenAIImageGenerator().generate(
            image_prompt, CHANNEL_IMAGE_SPECS["instagram_feed"]
        )
        image_path = _host_image_publicly(local_image_path)
    return text, image_path


_ACTIVE_DRAFT_STATUSES = (ReviewStatus.PENDING, ReviewStatus.APPROVED, ReviewStatus.PUBLISHED)


def generate_drafts(product: Product, channels: list[str] | None = None) -> list[ContentDraft]:
    """상품 하나에 대해 채널별 콘텐츠 초안을 생성하고 검수 대기열에 넣는다.

    이미 검수 대기/승인/발행 상태인 초안이 있는 (product, channel) 조합은
    건너뛴다. `autocpna generate`는 매번 DB에 저장된 상위 N개 상품을 다시
    조회하므로, 이 스킵이 없으면 같은 상품이 계속 상위권에 남아있는 동안
    반복 실행할 때마다 중복 초안이 쌓인다. 반려된 초안만 있는 경우는
    regenerate_draft가 처리하는 별도 경로이므로 여기서는 새로 생성한다.
    """
    channels_cfg = get_channels_config()
    channels = channels or [c for c, cfg in channels_cfg.items() if cfg.get("enabled")]

    with get_session() as session:
        already_active = {
            d.channel
            for d in session.query(ContentDraft)
            .filter(
                ContentDraft.product_id == product.id,
                ContentDraft.status.in_(_ACTIVE_DRAFT_STATUSES),
            )
            .all()
        }
    channels_to_generate = [c for c in channels if c not in already_active]

    drafts: list[ContentDraft] = []
    with get_session() as session:
        for channel in channels_to_generate:
            text, image_path = _generate_channel_content(product, channel)
            draft = ContentDraft(
                product_id=product.id,
                channel=channel,
                caption_or_body=text,
                image_path=image_path,
                status=ReviewStatus.PENDING,
            )
            session.add(draft)
            drafts.append(draft)
        session.commit()
        for d in drafts:
            session.refresh(d)
    return drafts


def regenerate_draft(draft_id: int) -> ContentDraft:
    """반려된 초안을 검수자 반려 사유(reviewer_note)를 반영해 다시 생성.

    기존 반려 초안은 이력 보존을 위해 그대로 두고, 새 PENDING 초안을
    추가한다 (아키텍처상 반려 -> 폐기/재생성 경로).

    주의: generate_blog_comparison_draft로 만든 'OO 추천 TOP N' 비교글은
    지원하지 않는다 - 그 채널은 여러 상품을 묶어 만들지만 ContentDraft에는
    대표 상품 하나(product_id)만 연결되어 있어, 여기서 재생성하면 비교글이
    아니라 그 대표 상품 단일 리뷰로 바뀌어버린다. 비교글을 다시 만들려면
    generate_blog_comparison_draft를 다시 호출할 것.
    """
    with get_session() as session:
        old_draft = session.get(ContentDraft, draft_id)
        if old_draft is None:
            raise ValueError(f"draft {draft_id} not found")
        if old_draft.status != ReviewStatus.REJECTED:
            raise ValueError(f"draft {draft_id} is not rejected (status={old_draft.status})")
        product = session.get(Product, old_draft.product_id)
        if product is None:
            raise ValueError(f"draft {draft_id}의 product {old_draft.product_id}를 찾을 수 없습니다")
        channel = old_draft.channel
        feedback = old_draft.reviewer_note

    text, image_path = _generate_channel_content(product, channel, feedback=feedback)

    with get_session() as session:
        new_draft = ContentDraft(
            product_id=product.id,
            channel=channel,
            caption_or_body=text,
            image_path=image_path,
            status=ReviewStatus.PENDING,
        )
        session.add(new_draft)
        session.commit()
        session.refresh(new_draft)
    return new_draft


def generate_blog_comparison_draft(topic: str, products: list[Product]) -> ContentDraft:
    """네이버 블로그용 'OO 추천 TOP N' 비교 콘텐츠 초안 생성.

    ContentDraft.product_id는 단일 FK라 여러 상품을 모두 연결할 수 없으므로,
    검수 시 참고용으로 대표 상품(첫 번째, 보통 최고 점수)에만 연결한다.
    나머지 상품 정보는 caption_or_body 본문 안에 이미 포함되어 있다.
    """
    if not products:
        raise ValueError("products가 비어 있습니다")

    generator = BlogGenerator()
    product_dicts = [_product_to_dict(p) for p in products]
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


def publish_approved_draft(draft_id: int) -> PublishResult:
    """승인된 초안을 발행하고, 성공/실패와 무관하게 PublishLog에 결과를 남긴다.

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
        session.add(
            PublishLog(
                draft_id=draft.id,
                channel=draft.channel,
                success=result.success,
                remote_post_id=result.remote_post_id,
                error_message=result.error_message,
            )
        )
        session.commit()
    return result
