"""Facebook 페이지 발행기 (Meta Graph API).

https://developers.facebook.com/docs/pages-api
Instagram과 같은 Meta Page 액세스 토큰을 재사용하지만, 대상 ID는 다르다 -
Instagram은 IG 비즈니스 계정 ID(META_IG_BUSINESS_ID), Facebook은 페이지
자체의 ID(META_PAGE_ID)를 쓴다.
"""
from __future__ import annotations

import httpx

from autocpna.config import get_settings
from autocpna.publish.base import PublishResult, Publisher, graph_api_error_message

GRAPH_API_BASE = "https://graph.facebook.com/v26.0"


class FacebookPublisher(Publisher):
    channel = "facebook"

    def __init__(self) -> None:
        settings = get_settings()
        self.access_token = settings.meta_page_access_token
        self.page_id = settings.meta_page_id

    def publish(self, draft) -> PublishResult:
        try:
            with httpx.Client(base_url=GRAPH_API_BASE) as client:
                resp = client.post(
                    f"/{self.page_id}/feed",
                    params={
                        "message": draft.caption_or_body,
                        "access_token": self.access_token,
                    },
                )
                resp.raise_for_status()
                post_id = resp.json()["id"]

            return PublishResult(success=True, remote_post_id=post_id)
        except httpx.HTTPError as exc:
            return PublishResult(success=False, error_message=graph_api_error_message(exc))
