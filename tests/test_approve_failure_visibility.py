"""자동 발행 채널에서 승인 후 발행이 실패하면, 상태만으로는 "발행이 아직 시도
안 됨"과 "시도했지만 실패함"을 구분할 수 없다(둘 다 ContentDraft.status가
APPROVED로 남는다). review_queue.should_auto_publish + PublishLog 조회로
CLI/대시보드가 실패 사실과 사유를 정확히 보여주는지 확인."""
from click.testing import CliRunner

from autocpna.cli import cli
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


def test_should_auto_publish_true_for_auto_channel(monkeypatch):
    monkeypatch.setattr(
        "autocpna.review.queue.get_channels_config",
        lambda: {"threads": {"requires_review": False}},
    )
    assert review_queue.should_auto_publish("threads") is True


def test_should_auto_publish_false_when_requires_review(monkeypatch):
    monkeypatch.setattr(
        "autocpna.review.queue.get_channels_config",
        lambda: {"threads": {"requires_review": True}},
    )
    assert review_queue.should_auto_publish("threads") is False


def test_cli_approve_reports_auto_publish_failure_reason(fresh_db, monkeypatch):
    monkeypatch.setattr(
        "autocpna.review.queue.get_channels_config",
        lambda: {"threads": {"requires_review": False}},
    )

    class FailingPublisher:
        def publish(self, draft):
            return PublishResult(success=False, error_message="token expired")

    monkeypatch.setitem(orchestrator.PUBLISHERS, "threads", FailingPublisher)

    draft_id = _make_pending_draft("threads")
    result = CliRunner().invoke(cli, ["review", "approve", str(draft_id)])

    assert "실패" in result.output
    assert "token expired" in result.output

    with get_session() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.status == ReviewStatus.APPROVED  # 실패했으니 PUBLISHED로 안 바뀜


def test_cli_approve_reports_success_when_auto_published(fresh_db, monkeypatch):
    monkeypatch.setattr(
        "autocpna.review.queue.get_channels_config",
        lambda: {"threads": {"requires_review": False}},
    )

    class SucceedingPublisher:
        def publish(self, draft):
            return PublishResult(success=True, remote_post_id="post-1")

    monkeypatch.setitem(orchestrator.PUBLISHERS, "threads", SucceedingPublisher)

    draft_id = _make_pending_draft("threads")
    result = CliRunner().invoke(cli, ["review", "approve", str(draft_id)])

    assert "자동 발행 완료" in result.output


def test_cli_approve_reports_manual_publish_needed(fresh_db, monkeypatch):
    monkeypatch.setattr(
        "autocpna.review.queue.get_channels_config",
        lambda: {"threads": {"requires_review": True}},
    )

    draft_id = _make_pending_draft("threads")
    result = CliRunner().invoke(cli, ["review", "approve", str(draft_id)])

    assert "별도로 트리거 필요" in result.output
