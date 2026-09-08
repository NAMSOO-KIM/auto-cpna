"""채널별 생성 콘텐츠 초안 + 검수 상태."""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from autocpna.db import Base


class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class ContentDraft(Base):
    __tablename__ = "content_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    channel: Mapped[str] = mapped_column(String)  # instagram / threads / naver_blog
    caption_or_body: Mapped[str] = mapped_column(Text)
    hashtags: Mapped[str] = mapped_column(String, default="")
    image_path: Mapped[str] = mapped_column(String, default="")
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.PENDING
    )
    reviewer_note: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(default=None)
