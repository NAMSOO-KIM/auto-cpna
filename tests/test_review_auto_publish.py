from autocpna.db import get_session
from autocpna.models.content_draft import ContentDraft, ReviewStatus
from autocpna.models.product import Product
from autocpna.pipeline import orchestrator
from autocpna.publish.base import PublishResult
from autocpna.review import queue as review_queue


def _make_pending_draft(channel: str) -> int:
    with get_session() as session:
        product = Product(external_id="ext-1", name="상품", category="cat", price=1000)
        session.add(product)
        session.commit()
        session.refresh(product)

        draft = ContentDraft(
            product_id=product.id,
            channel=channel,
            caption_or_body="본문",
            status=ReviewStatus.PENDING,
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        return draft.id


def test_requires_review_channel_does_not_auto_publish(fresh_db, monkeypatch):
    monkeypatch.setattr(
        "autocpna.review.queue.get_channels_config",
        lambda: {"threads": {"requires_review": True}},
    )
    called = []
    monkeypatch.setattr(
        "autocpna.pipeline.orchestrator.publish_approved_draft",
        lambda draft_id: called.append(draft_id),
    )

    draft_id = _make_pending_draft("threads")
    draft = review_queue.approve(draft_id)

    assert draft.status == ReviewStatus.APPROVED
    assert called == []


def test_requires_review_false_auto_publishes(fresh_db, monkeypatch):
    monkeypatch.setattr(
        "autocpna.review.queue.get_channels_config",
        lambda: {"threads": {"requires_review": False}},
    )

    class FakePublisher:
        def publish(self, draft):
            return PublishResult(success=True, remote_post_id="post-1")

    monkeypatch.setitem(orchestrator.PUBLISHERS, "threads", FakePublisher)

    draft_id = _make_pending_draft("threads")
    draft = review_queue.approve(draft_id)

    assert draft.status == ReviewStatus.PUBLISHED


def test_auto_publish_false_blocks_even_when_requires_review_false(fresh_db, monkeypatch):
    """naver_blog 같은 채널의 코드 레벨 안전장치: requires_review가 false로
    잘못 설정돼도 auto_publish:false가 자동 발행을 한 번 더 막아야 한다."""
    monkeypatch.setattr(
        "autocpna.review.queue.get_channels_config",
        lambda: {"naver_blog": {"requires_review": False, "auto_publish": False}},
    )
    called = []
    monkeypatch.setattr(
        "autocpna.pipeline.orchestrator.publish_approved_draft",
        lambda draft_id: called.append(draft_id),
    )

    draft_id = _make_pending_draft("naver_blog")
    draft = review_queue.approve(draft_id)

    assert draft.status == ReviewStatus.APPROVED
    assert called == []
