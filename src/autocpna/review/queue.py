"""사람 검수 큐. ContentDraft.status 를 CLI/대시보드에서 조작."""
from __future__ import annotations

import datetime as dt

from autocpna.config import get_channels_config
from autocpna.db import get_session
from autocpna.models.content_draft import ContentDraft, ReviewStatus
from autocpna.models.publish_log import PublishLog


def should_auto_publish(channel: str) -> bool:
    """channels.yaml 기준으로 승인 즉시 자동 발행할지 판단.

    requires_review가 true(기본값)면 항상 사람이 별도로 publish를 트리거해야
    한다. auto_publish는 naver_blog처럼 코드 레벨에서도 자동 발행을 한 번 더
    강제 차단하려는 채널을 위한 보조 플래그 (기본값 true).

    대시보드/CLI가 승인 후 안내 문구를 고를 때도 이 함수로 "자동 발행이
    시도되는 채널인지"를 판단한다 - 그래야 자동 발행이 실패했을 때 "수동으로
    발행하세요"가 아니라 "자동 발행을 시도했지만 실패했다"고 정확히 알릴 수
    있다 (둘 다 승인 후 status는 APPROVED로 남아 구분이 안 되기 때문).
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


def list_rejected() -> list[ContentDraft]:
    with get_session() as session:
        return (
            session.query(ContentDraft)
            .filter(ContentDraft.status == ReviewStatus.REJECTED)
            .all()
        )


def list_approved(channel: str | None = None) -> list[ContentDraft]:
    """승인됐지만 아직 발행되지 않은 초안. channel을 주면 그 채널만.

    네이버 블로그처럼 자동 발행이 불가능한 채널은 승인 후 계속 APPROVED로
    남으므로, 사람이 직접 올려야 할 목록을 뽑는 용도로 쓴다.
    """
    with get_session() as session:
        query = session.query(ContentDraft).filter(
            ContentDraft.status == ReviewStatus.APPROVED
        )
        if channel is not None:
            query = query.filter(ContentDraft.channel == channel)
        return query.all()


def mark_published(draft_id: int) -> ContentDraft:
    """사람이 채널에 직접 올린 초안을 발행 완료로 넘긴다.

    자동 발행이 없는 채널(네이버 블로그)은 이 경로가 없으면 승인 상태로 영원히
    쌓이기만 한다. 자동 발행과 동일하게 PublishLog에도 기록을 남겨서 발행
    이력이 한 곳에서 보이도록 한다.
    """
    with get_session() as session:
        draft = session.get(ContentDraft, draft_id)
        if draft is None:
            raise ValueError(f"draft {draft_id} not found")
        if draft.status != ReviewStatus.APPROVED:
            raise ValueError(f"draft {draft_id} is not approved (status={draft.status})")
        draft.status = ReviewStatus.PUBLISHED
        session.add(
            PublishLog(
                draft_id=draft.id,
                channel=draft.channel,
                success=True,
                remote_post_id="manual",
            )
        )
        session.commit()
        session.refresh(draft)
        return draft


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

    if should_auto_publish(channel):
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
