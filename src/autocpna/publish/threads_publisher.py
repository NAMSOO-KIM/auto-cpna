"""Threads 발행기 (Meta Threads API).

https://developers.facebook.com/docs/threads
Threads API는 게시 빈도 제한이 있으므로 오케스트레이터에서 호출 간격 조절 필요.
"""
from __future__ import annotations

import httpx

from autocpna.config import get_settings
from autocpna.publish.base import PublishResult, Publisher

THREADS_API_BASE = "https://graph.threads.net/v1.0"


class ThreadsPublisher(Publisher):
    channel = "threads"

    def __init__(self) -> None:
        settings = get_settings()
        self.access_token = settings.meta_page_access_token
        self.user_id = settings.meta_threads_user_id

    def publish(self, draft) -> PublishResult:
        try:
            with httpx.Client(base_url=THREADS_API_BASE) as client:
                container_resp = client.post(
                    f"/{self.user_id}/threads",
                    params={
                        "media_type": "TEXT",
                        "text": draft.caption_or_body,
                        "access_token": self.access_token,
                    },
                )
                container_resp.raise_for_status()
                creation_id = container_resp.json()["id"]

                publish_resp = client.post(
                    f"/{self.user_id}/threads_publish",
                    params={
                        "creation_id": creation_id,
                        "access_token": self.access_token,
                    },
                )
                publish_resp.raise_for_status()
                post_id = publish_resp.json()["id"]

            return PublishResult(success=True, remote_post_id=post_id)
        except httpx.HTTPError as exc:
            return PublishResult(success=False, error_message=str(exc))
