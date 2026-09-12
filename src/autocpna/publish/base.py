"""채널 발행기 공통 인터페이스."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


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


def graph_api_error_message(exc: httpx.HTTPError) -> str:
    """Meta Graph API 에러 응답의 error.message를 최대한 뽑아낸다.

    Graph API는 4xx/5xx에서도 본문에 {"error": {"message": "...", "code": ...}}
    형태로 사람이 읽을 수 있는 실패 사유를 담아 보내는데, str(exc)만으로는
    HTTP 상태 코드만 보이고 이 메시지는 사라진다.
    """
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            detail = response.json().get("error", {}).get("message")
        except ValueError:
            detail = None
        if detail:
            return detail
    return str(exc)
