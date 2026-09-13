"""CLI 진입점 (`autocpna` 커맨드)."""
from __future__ import annotations

import click

from autocpna.db import init_db
from autocpna.models.product import Product
from autocpna.pipeline.orchestrator import (
    collect_and_score,
    generate_blog_comparison_draft,
    generate_drafts,
    publish_approved_draft,
    regenerate_draft,
    register_manual_product,
)
from autocpna.review import queue as review_queue


@click.group()
def cli() -> None:
    init_db()


@cli.command()
@click.option("--keyword", default="", help="검색 키워드")
@click.option("--top", "top_n", default=20, help="상위 몇 개까지 저장할지")
def score(keyword: str, top_n: int) -> None:
    """상품 수집 + 점수화."""
    products = collect_and_score(keyword=keyword, top_n=top_n)
    for p in products:
        click.echo(f"[{p.score:.3f}] {p.name} ({p.category})")


@cli.command()
@click.option("--top", "top_n", default=10, help="점수 상위 몇 개 상품에 콘텐츠 생성할지")
def generate(top_n: int) -> None:
    """점수 상위 상품에 대해 채널별 콘텐츠 초안 생성."""
    from autocpna.db import get_session

    with get_session() as session:
        products = (
            session.query(Product).order_by(Product.score.desc()).limit(top_n).all()
        )
        for product in products:
            drafts = generate_drafts(product)
            click.echo(f"{product.name}: {len(drafts)}개 초안 생성")


@cli.command("generate-comparison")
@click.option("--topic", required=True, help="비교 주제 (예: '무선 이어폰')")
@click.option("--category", required=True, help="Product.category 필터 값")
@click.option("--top", "top_n", default=5, help="비교에 포함할 상품 개수")
def generate_comparison(topic: str, category: str, top_n: int) -> None:
    """같은 카테고리 상위 상품들을 묶어 'OO 추천 TOP N' 블로그 초안 생성."""
    from autocpna.db import get_session

    with get_session() as session:
        products = (
            session.query(Product)
            .filter(Product.category == category)
            .order_by(Product.score.desc())
            .limit(top_n)
            .all()
        )
        if not products:
            click.echo(f"카테고리 '{category}'에 저장된 상품이 없습니다. 먼저 score를 실행하세요.")
            return

    draft = generate_blog_comparison_draft(topic, products)
    click.echo(f"비교 콘텐츠 초안 #{draft.id} 생성됨 ({len(products)}개 상품 비교)")


@cli.command("add-product")
@click.option("--name", required=True, help="상품명")
@click.option("--category", required=True, help="카테고리")
@click.option("--price", type=float, required=True, help="가격(원)")
@click.option("--url", "product_url", required=True, help="쇼핑커넥트 등에서 발급받은 상품 링크")
@click.option("--margin-rate", type=float, required=True, help="수수료율 (예: 0.1 = 10%)")
@click.option(
    "--source",
    default="naver_shopping_connect",
    help="제휴 프로그램 식별자 (content_gen의 제휴 고지 문구 선택에 쓰임)",
)
@click.option("--keyword", default="", help="네이버 데이터랩 트렌드 조회용 키워드 (선택)")
def add_product(
    name: str, category: str, price: float, product_url: str, margin_rate: float, source: str, keyword: str
) -> None:
    """공개 수집 API가 없는 제휴 프로그램(네이버 쇼핑커넥트 등) 상품을 수동 등록.

    쿠팡파트너스는 `score` 명령으로 자동 수집되지만, 네이버 쇼핑커넥트는
    크리에이터가 직접 상품을 고르고 링크/수수료율을 확인하는 구조라 API가
    없다. 쇼핑커넥트 화면에서 확인한 값을 그대로 이 명령에 입력하면, 이후
    콘텐츠 생성/검수/발행은 쿠팡 상품과 동일한 파이프라인을 탄다.
    """
    product = register_manual_product(
        name=name,
        category=category,
        price=price,
        product_url=product_url,
        margin_rate=margin_rate,
        source=source,
        keyword=keyword,
    )
    click.echo(f"#{product.id} 등록됨 [{product.source}] (score={product.score:.3f})")


@cli.group()
def review() -> None:
    """검수 대기열 관리."""


@review.command("list")
def review_list() -> None:
    for draft in review_queue.list_pending():
        click.echo(f"#{draft.id} [{draft.channel}] {draft.caption_or_body[:60]}...")


@review.command("edit")
@click.argument("draft_id", type=int)
@click.option("--body", default=None, help="본문 전체를 이 값으로 교체")
@click.option("--hashtags", default=None, help="해시태그를 이 값으로 교체")
def review_edit(draft_id: int, body: str | None, hashtags: str | None) -> None:
    review_queue.update_content(draft_id, caption_or_body=body, hashtags=hashtags)
    click.echo(f"#{draft_id} 수정됨")


@review.command("approve")
@click.argument("draft_id", type=int)
@click.option("--note", default="")
def review_approve(draft_id: int, note: str) -> None:
    review_queue.approve(draft_id, note)
    click.echo(f"#{draft_id} 승인됨")


@review.command("reject")
@click.argument("draft_id", type=int)
@click.option("--note", default="", help="반려 사유 (재생성 시 이 내용이 프롬프트에 반영됨)")
def review_reject(draft_id: int, note: str) -> None:
    review_queue.reject(draft_id, note)
    click.echo(f"#{draft_id} 반려됨")


@review.command("rejected")
def review_rejected() -> None:
    """반려된 초안 목록 (재생성 대상)."""
    for draft in review_queue.list_rejected():
        note = f" - 사유: {draft.reviewer_note}" if draft.reviewer_note else ""
        click.echo(f"#{draft.id} [{draft.channel}]{note}")


@review.command("regenerate")
@click.argument("draft_id", type=int)
def review_regenerate(draft_id: int) -> None:
    """반려된 초안을 반려 사유를 반영해 다시 생성 (새 PENDING 초안 추가)."""
    new_draft = regenerate_draft(draft_id)
    click.echo(f"#{draft_id} -> #{new_draft.id} 재생성됨 (검수 대기)")


@cli.command()
@click.option("--draft-id", type=int, required=True)
def publish(draft_id: int) -> None:
    """승인된 초안 발행."""
    result = publish_approved_draft(draft_id)
    if result.success:
        click.echo(f"#{draft_id} 발행 완료 (remote_post_id={result.remote_post_id})")
    else:
        click.echo(f"#{draft_id} 발행 실패: {result.error_message}")


if __name__ == "__main__":
    cli()
