"""Cloudinary 업로드 커넥터.

Instagram Graph API의 미디어 컨테이너 생성(`/media`)은 image_url이 Meta 서버가
직접 fetch할 수 있는 공개 HTTPS URL이어야 한다 (로컬 파일 업로드 불가). 이
모듈은 OpenAIImageGenerator 등이 로컬에 만든 이미지를 Cloudinary에 올려
그 요건을 만족하는 URL(secure_url)로 바꿔준다.

인증: signed upload (https://cloudinary.com/documentation/authentication_signatures).
서명 대상 = file/cloud_name/api_key/signature/resource_type을 제외한 나머지
파라미터를 key로 알파벳 정렬해 "k=v&k=v..."로 이어붙인 뒤 api_secret을
그대로 뒤에 붙이고 SHA-1 해시.
"""
from __future__ import annotations

import hashlib
import time

import httpx

from autocpna.config import get_settings

UPLOAD_URL_TEMPLATE = "https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"


def _sign(params: dict[str, str], api_secret: str) -> str:
    to_sign = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.sha1((to_sign + api_secret).encode("utf-8")).hexdigest()


class CloudinaryUploader:
    def __init__(self) -> None:
        settings = get_settings()
        self.cloud_name = settings.cloudinary_cloud_name
        self.api_key = settings.cloudinary_api_key
        self.api_secret = settings.cloudinary_api_secret

    @property
    def configured(self) -> bool:
        return bool(self.cloud_name and self.api_key and self.api_secret)

    def upload(self, local_path: str, folder: str = "autocpna") -> str:
        """로컬 이미지를 업로드하고 공개 HTTPS URL(secure_url)을 반환."""
        params_to_sign = {"timestamp": str(int(time.time())), "folder": folder}
        data = {
            **params_to_sign,
            "api_key": self.api_key,
            "signature": _sign(params_to_sign, self.api_secret),
        }
        url = UPLOAD_URL_TEMPLATE.format(cloud_name=self.cloud_name)
        with open(local_path, "rb") as image_file:
            with httpx.Client(timeout=30) as client:
                resp = client.post(url, data=data, files={"file": image_file})
                resp.raise_for_status()
        return resp.json()["secure_url"]
