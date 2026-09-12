"""사람 검수 큐. ContentDraft.status 를 CLI/대시보드에서 조작."""
from __future__ import annotations

import datetime as dt

from autocpna.config import get_channels_config
from autocpna.db import get_session
from autocpna.models.content_draft import ContentDraft, ReviewStatus


def _should_auto_publish(channel: str) -> bool:
    """channels.yaml 기준으로 승인 즉시 자동 발행할지 판단.

    requires_review가 true(기본값)면 항상 사람이 별도로 publish를 트리거해야
    한다. auto_publish는 naver_blog처럼 코드 레벨에서도 자동 발행을 한 번 더
    강제 차단하려는 채널을 위한 보조 플래그 (기본값 true).
    """
    channel_cfg = get_channels_config().get(channel, {})
    if channel_cfg.get("requires_review", True):
        return False
    return channel_cfg.get("auto_publish", True)


def list_pending() -> list[ContentDraft]:
    with get_session() as session:
        return (
            session.query(ContentDraft)
            .filter(ContentDraft.status == ReviewStatus.PENDING)
            .all()
        )


def update_content(
    draft_id: int,
    caption_or_body: str | None = None,
    hashtags: str | None = None,
) -> ContentDraft:
    """검수자가 발행 전 캡션/해시태그를 직접 수정할 때 사용. None인 필드는 유지."""
    with get_session() as session:
        draft = session.get(ContentDraft, draft_id)
        if draft is None:
            raise ValueError(f"draft {draft_id} not found")
        if caption_or_body is not None:
            draft.caption_or_body = caption_or_body
        if hashtags is not None:
            draft.hashtags = hashtags
        session.commit()
        session.refresh(draft)
        return draft


def approve(draft_id: int, note: str = "") -> ContentDraft:
    """초안을 승인한다. 해당 채널이 requires_review=false(+auto_publish!=false)면
    승인 즉시 발행까지 트리거한다 (channels.yaml 참고)."""
    with get_session() as session:
        draft = session.get(ContentDraft, draft_id)
        if draft is None:
            raise ValueError(f"draft {draft_id} not found")
        draft.status = ReviewStatus.APPROVED
        draft.reviewer_note = note
        draft.reviewed_at = dt.datetime.utcnow()
        session.commit()
        session.refresh(draft)
        channel = draft.channel

    if _should_auto_publish(channel):
        from autocpna.pipeline.orchestrator import publish_approved_draft

        publish_approved_draft(draft_id)
        with get_session() as session:
            draft = session.get(ContentDraft, draft_id)

    return draft


def reject(draft_id: int, note: str = "") -> ContentDraft:
    with get_session() as session:
        draft = session.get(ContentDraft, draft_id)
        if draft is None:
            raise ValueError(f"draft {draft_id} not found")
        draft.status = ReviewStatus.REJECTED
        draft.reviewer_note = note
        draft.reviewed_at = dt.datetime.utcnow()
        session.commit()
        session.refresh(draft)
        return draft
