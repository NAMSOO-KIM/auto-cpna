"""Threads 발행기 (Meta Threads API).

https://developers.facebook.com/docs/threads
Threads API는 게시 빈도 제한이 있으므로 오케스트레이터에서 호출 간격 조절 필요.

Threads API는 Instagram/Facebook Graph API와 별개의 OAuth 플로우
(threads_basic, threads_content_publish 스코프)로 발급된 전용 액세스 토큰을
사용한다 - Meta Page 액세스 토큰(META_PAGE_ACCESS_TOKEN)을 재사용할 수 없다.
"""
from __future__ import annotations

import httpx

from autocpna.config import get_settings
from autocpna.publish.base import PublishResult, Publisher, graph_api_error_message

THREADS_API_BASE = "https://graph.threads.net/v1.0"


class ThreadsPublisher(Publisher):
    channel = "threads"

    def __init__(self) -> None:
        settings = get_settings()
        self.access_token = settings.meta_threads_access_token
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
            return PublishResult(success=False, error_message=graph_api_error_message(exc))
