"""OpenAI(gpt-image-1) 기반 이미지 생성기.

https://platform.openai.com/docs/guides/images
gpt-image-1은 1024x1024 / 1024x1536(세로) / 1536x1024(가로) 세 가지 크기만
지원하므로, 채널이 요구하는 픽셀 규격(CHANNEL_IMAGE_SPECS)은 종횡비 기준으로
가장 가까운 지원 크기에 매핑한다. 응답은 항상 base64(PNG)로 온다.
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

import httpx

from autocpna.config import get_settings
from autocpna.media_gen.image_generator import ImageGenerator

API_URL = "https://api.openai.com/v1/images/generations"
MODEL = "gpt-image-1"

_SUPPORTED_SIZES = {
    "square": "1024x1024",
    "portrait": "1024x1536",
    "landscape": "1536x1024",
}


def _nearest_supported_size(width: int, height: int) -> str:
    ratio = width / height
    if ratio > 1.1:
        return _SUPPORTED_SIZES["landscape"]
    if ratio < 0.9:
        return _SUPPORTED_SIZES["portrait"]
    return _SUPPORTED_SIZES["square"]


class OpenAIImageGenerator(ImageGenerator):
    def __init__(self, output_dir: str = "media_output/images") -> None:
        self.api_key = get_settings().image_gen_api_key
        self.output_dir = Path(output_dir)

    def generate(self, prompt: str, size: tuple[int, int]) -> str:
        openai_size = _nearest_supported_size(*size)
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": MODEL, "prompt": prompt, "size": openai_size, "n": 1},
            )
            resp.raise_for_status()
            b64_data = resp.json()["data"][0]["b64_json"]

        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.output_dir / f"{int(time.time() * 1000)}.png"
        out_path.write_bytes(base64.b64decode(b64_data))
        return str(out_path)
