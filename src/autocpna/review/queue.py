"""사람 검수 큐. ContentDraft.status 를 CLI/대시보드에서 조작."""
from __future__ import annotations

import datetime as dt

from autocpna.db import get_session
from autocpna.models.content_draft import ContentDraft, ReviewStatus


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
    with get_session() as session:
        draft = session.get(ContentDraft, draft_id)
        if draft is None:
            raise ValueError(f"draft {draft_id} not found")
        draft.status = ReviewStatus.APPROVED
        draft.reviewer_note = note
        draft.reviewed_at = dt.datetime.utcnow()
        session.commit()
        session.refresh(draft)
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
