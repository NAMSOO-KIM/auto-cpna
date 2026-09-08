"""Instagram 발행기 (Meta Graph API, 비즈니스 계정 필요).

공식 흐름: 1) 이미지 컨테이너 생성 2) 컨테이너 발행
https://developers.facebook.com/docs/instagram-api/guides/content-publishing
"""
from __future__ import annotations

import httpx

from autocpna.config import get_settings
from autocpna.publish.base import PublishResult, Publisher

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class InstagramPublisher(Publisher):
    channel = "instagram"

    def __init__(self) -> None:
        settings = get_settings()
        self.access_token = settings.meta_page_access_token
        self.ig_business_id = settings.meta_ig_business_id

    def publish(self, draft) -> PublishResult:
        try:
            with httpx.Client(base_url=GRAPH_API_BASE) as client:
                container_resp = client.post(
                    f"/{self.ig_business_id}/media",
                    params={
                        "image_url": draft.image_path,
                        "caption": f"{draft.caption_or_body}\n\n{draft.hashtags}",
                        "access_token": self.access_token,
                    },
                )
                container_resp.raise_for_status()
                creation_id = container_resp.json()["id"]

                publish_resp = client.post(
                    f"/{self.ig_business_id}/media_publish",
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
