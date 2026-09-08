"""이미지 자동 생성/편집 인터페이스.

제공자가 아직 확정되지 않아 인터페이스만 정의. 실제 사용 시
ImageGenerator를 상속해 구현체(예: 특정 이미지 생성 API 래퍼)를 추가하고
pipeline/orchestrator.py 에서 주입.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

# 채널별 권장 이미지 규격 (실제 값은 각 플랫폼 최신 가이드 기준으로 갱신 필요)
CHANNEL_IMAGE_SPECS = {
    "instagram_feed": (1080, 1350),
    "instagram_story": (1080, 1920),
    "threads": (1080, 1080),
}


class ImageGenerator(ABC):
    @abstractmethod
    def generate(self, prompt: str, size: tuple[int, int]) -> str:
        """이미지를 생성하고 로컬 파일 경로를 반환.

        prompt: 상품 무드/컨셉을 설명하는 텍스트
        size: (width, height)
        """
        raise NotImplementedError


class NotConfiguredImageGenerator(ImageGenerator):
    """제공자 미설정 시 기본으로 사용되는 플레이스홀더. 호출 시 명시적으로 에러."""

    def generate(self, prompt: str, size: tuple[int, int]) -> str:
        raise NotImplementedError(
            "이미지 생성 제공자가 설정되지 않았습니다. "
            "ImageGenerator를 상속한 구현체를 만들어 orchestrator에 주입하세요."
        )
