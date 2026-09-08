"""수집 커넥터 공통 인터페이스."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DataSource(ABC):
    """모든 외부 데이터 소스 커넥터가 구현해야 하는 인터페이스."""

    @abstractmethod
    def fetch(self, **kwargs: Any) -> list[dict]:
        """원본 데이터를 dict 리스트로 반환. 스코어링 엔진이 기대하는 키는
        각 서브클래스 docstring 참고."""
        raise NotImplementedError
