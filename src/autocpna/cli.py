"""CLI 진입점 (`autocpna` 커맨드)."""
from __future__ import annotations

import click

from autocpna.db import init_db
from autocpna.models.product import Product
from autocpna.pipeline.orchestrator import (
    collect_and_score,
    generate_drafts,
    publish_approved_draft,
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


@cli.group()
def review() -> None:
    """검수 대기열 관리."""


@review.command("list")
def review_list() -> None:
    for draft in review_queue.list_pending():
        click.echo(f"#{draft.id} [{draft.channel}] {draft.caption_or_body[:60]}...")


@review.command("approve")
@click.argument("draft_id", type=int)
@click.option("--note", default="")
def review_approve(draft_id: int, note: str) -> None:
    review_queue.approve(draft_id, note)
    click.echo(f"#{draft_id} 승인됨")


@review.command("reject")
@click.argument("draft_id", type=int)
@click.option("--note", default="")
def review_reject(draft_id: int, note: str) -> None:
    review_queue.reject(draft_id, note)
    click.echo(f"#{draft_id} 반려됨")


@cli.command()
@click.option("--draft-id", type=int, required=True)
def publish(draft_id: int) -> None:
    """승인된 초안 발행."""
    publish_approved_draft(draft_id)
    click.echo(f"#{draft_id} 발행 처리 완료")


if __name__ == "__main__":
    cli()
