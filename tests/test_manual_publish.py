"""승인 후 사람이 직접 올려야 하는 채널(네이버 블로그)의 마무리 경로.

이 경로가 없으면 승인된 블로그 초안이 APPROVED 상태로 영원히 쌓이기만 한다.
"""
import pytest

from autocpna.db import get_session
from autocpna.models.content_draft import ContentDraft, ReviewStatus
from autocpna.models.product import Product
from autocpna.models.publish_log import PublishLog
from autocpna.review import queue as review_queue


def _make_draft(channel: str, status: ReviewStatus) -> int:
    with get_session() as session:
        product = Product(external_id=f"ext-{channel}-{status.value}", name="상품", category="c", price=1000)
        session.add(product)
        session.commit()
        session.refresh(product)

        draft = ContentDraft(
            product_id=product.id, channel=channel, caption_or_body="본문", status=status
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        return draft.id


def test_list_approved_filters_by_channel(fresh_db):
    blog_id = _make_draft("naver_blog", ReviewStatus.APPROVED)
    _make_draft("threads", ReviewStatus.APPROVED)
    _make_draft("naver_blog", ReviewStatus.PENDING)  # 승인 전은 제외

    approved = review_queue.list_approved(channel="naver_blog")

    assert [d.id for d in approved] == [blog_id]


def test_list_approved_without_channel_returns_all(fresh_db):
    _make_draft("naver_blog", ReviewStatus.APPROVED)
    _make_draft("threads", ReviewStatus.APPROVED)

    assert len(review_queue.list_approved()) == 2


def test_mark_published_sets_status_and_logs(fresh_db):
    draft_id = _make_draft("naver_blog", ReviewStatus.APPROVED)

    draft = review_queue.mark_published(draft_id)

    assert draft.status == ReviewStatus.PUBLISHED
    with get_session() as session:
        logs = session.query(PublishLog).filter(PublishLog.draft_id == draft_id).all()
        assert len(logs) == 1
        assert logs[0].success is True
        assert logs[0].remote_post_id == "manual"


def test_marked_draft_leaves_the_pending_list(fresh_db):
    draft_id = _make_draft("naver_blog", ReviewStatus.APPROVED)
    review_queue.mark_published(draft_id)

    assert review_queue.list_approved(channel="naver_blog") == []


def test_mark_published_rejects_non_approved_draft(fresh_db):
    draft_id = _make_draft("naver_blog", ReviewStatus.PENDING)

    with pytest.raises(ValueError, match="is not approved"):
        review_queue.mark_published(draft_id)
