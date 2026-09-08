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
