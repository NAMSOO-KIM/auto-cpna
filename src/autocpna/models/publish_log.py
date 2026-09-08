"""발행 결과 로그 (성과 추적용)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from autocpna.db import Base


class PublishLog(Base):
    __tablename__ = "publish_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("content_drafts.id"))
    channel: Mapped[str] = mapped_column(String)
    success: Mapped[bool] = mapped_column(default=False)
    remote_post_id: Mapped[str] = mapped_column(String, default="")
    error_message: Mapped[str] = mapped_column(String, default="")
    published_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
