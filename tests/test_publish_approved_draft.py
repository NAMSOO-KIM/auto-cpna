import pytest

from autocpna.db import get_session
from autocpna.models.content_draft import ContentDraft, ReviewStatus
from autocpna.models.product import Product
from autocpna.models.publish_log import PublishLog
from autocpna.pipeline import orchestrator
from autocpna.pipeline.orchestrator import publish_approved_draft
from autocpna.publish.base import PublishResult


def _make_approved_draft(channel: str = "threads") -> int:
    with get_session() as session:
        product = Product(external_id="ext-1", name="상품", category="cat", price=1000)
        session.add(product)
        session.commit()
        session.refresh(product)

        draft = ContentDraft(
            product_id=product.id,
            channel=channel,
            caption_or_body="본문",
            status=ReviewStatus.APPROVED,
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        return draft.id


def test_successful_publish_marks_published_and_logs(fresh_db, monkeypatch):
    class FakePublisher:
        def publish(self, draft):
            return PublishResult(success=True, remote_post_id="post-123")

    monkeypatch.setitem(orchestrator.PUBLISHERS, "threads", FakePublisher)

    draft_id = _make_approved_draft("threads")
    result = publish_approved_draft(draft_id)

    assert result.success is True
    assert result.remote_post_id == "post-123"

    with get_session() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.status == ReviewStatus.PUBLISHED

        logs = session.query(PublishLog).filter(PublishLog.draft_id == draft_id).all()
        assert len(logs) == 1
        assert logs[0].success is True
        assert logs[0].remote_post_id == "post-123"


def test_failed_publish_keeps_status_and_logs_error(fresh_db, monkeypatch):
    class FakePublisher:
        def publish(self, draft):
            return PublishResult(success=False, error_message="token expired")

    monkeypatch.setitem(orchestrator.PUBLISHERS, "threads", FakePublisher)

    draft_id = _make_approved_draft("threads")
    result = publish_approved_draft(draft_id)

    assert result.success is False
    assert result.error_message == "token expired"

    with get_session() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.status == ReviewStatus.APPROVED  # 발행 실패했으니 상태 유지

        logs = session.query(PublishLog).filter(PublishLog.draft_id == draft_id).all()
        assert len(logs) == 1
        assert logs[0].success is False
        assert logs[0].error_message == "token expired"


def test_raises_for_non_approved_draft(fresh_db):
    with get_session() as session:
        product = Product(external_id="ext-2", name="상품", category="cat", price=1000)
        session.add(product)
        session.commit()
        session.refresh(product)

        draft = ContentDraft(
            product_id=product.id,
            channel="threads",
            caption_or_body="본문",
            status=ReviewStatus.PENDING,
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        draft_id = draft.id

    with pytest.raises(ValueError, match="is not approved"):
        publish_approved_draft(draft_id)
