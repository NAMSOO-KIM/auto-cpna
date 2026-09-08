"""채널 발행기 공통 인터페이스."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PublishResult:
    success: bool
    remote_post_id: str = ""
    error_message: str = ""


class Publisher(ABC):
    channel: str

    @abstractmethod
    def publish(self, draft) -> PublishResult:
        """ContentDraft를 받아 실제 채널에 발행. draft.status는 이미
        ReviewStatus.APPROVED 상태여야 하며, 호출부(orchestrator)가 보장."""
        raise NotImplementedError
