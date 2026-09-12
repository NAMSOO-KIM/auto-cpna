"""Instagram 발행기 (Meta Graph API, 비즈니스 계정 필요).

공식 흐름: 1) 이미지 컨테이너 생성 2) 컨테이너 발행
https://developers.facebook.com/docs/instagram-api/guides/content-publishing

Graph API 버전은 출시 후 2년이 지나면 제거되므로 주기적으로 최신 버전으로
올려야 한다 (2026-09 기준 최신: v26.0).
"""
from __future__ import annotations

import httpx

from autocpna.config import get_settings
from autocpna.publish.base import PublishResult, Publisher, graph_api_error_message

GRAPH_API_BASE = "https://graph.facebook.com/v26.0"


class InstagramPublisher(Publisher):
    channel = "instagram"

    def __init__(self) -> None:
        settings = get_settings()
        self.access_token = settings.meta_page_access_token
        self.ig_business_id = settings.meta_ig_business_id

    def publish(self, draft) -> PublishResult:
        # 컨테이너 생성 API의 image_url은 Meta 서버가 직접 fetch할 수 있는
        # 공개 HTTPS URL이어야 한다 - 로컬 파일 경로(OpenAIImageGenerator가
        # media_output/images/에 저장한 값)를 그대로 보내면 Graph API가
        # 이미지를 가져오지 못해 실패한다. 사전에 걸러서 원인을 명확히 알린다.
        if not draft.image_path.startswith(("http://", "https://")):
            return PublishResult(
                success=False,
                error_message=(
                    "image_path가 공개 URL이 아닙니다: "
                    f"{draft.image_path!r}. Instagram 컨테이너 생성 API는 로컬 파일을 "
                    "받지 않으므로, 발행 전에 이미지를 공개적으로 접근 가능한 위치에 "
                    "업로드하고 그 URL로 교체해야 합니다."
                ),
            )

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
            return PublishResult(success=False, error_message=graph_api_error_message(exc))
