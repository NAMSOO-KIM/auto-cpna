"""네이버 데이터랩 (검색어 트렌드) API 커넥터.

공식 문서: https://developers.naver.com/docs/serviceapi/datalab/
인증: Client-Id / Client-Secret 헤더 방식.
"""
from __future__ import annotations

import httpx

from autocpna.config import get_settings
from autocpna.ingestion.base import DataSource

BASE_URL = "https://openapi.naver.com/v1/datalab/search"


class NaverDatalabClient(DataSource):
    """키워드별 검색량 추세를 반환.

    반환 dict 키: keyword, search_volume(상대 지수), trend_momentum(최근 대비 증감률)
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.client_id = settings.naver_datalab_client_id
        self.client_secret = settings.naver_datalab_client_secret

    def _headers(self) -> dict:
        return {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
            "Content-Type": "application/json",
        }

    def fetch(
        self,
        keywords: list[str] | None = None,
        start_date: str = "",
        end_date: str = "",
        time_unit: str = "week",
    ) -> list[dict]:
        """키워드 그룹 검색 트렌드 조회.

        TODO: 실제 응답의 results[].data 시계열을 받아 최근 구간 momentum을
        계산하는 로직은 스코어링 엔진과 합의된 정의에 맞춰 보정 필요.
        """
        keywords = keywords or []
        body = {
            "startDate": start_date,
            "endDate": end_date,
            "timeUnit": time_unit,
            "keywordGroups": [
                {"groupName": kw, "keywords": [kw]} for kw in keywords
            ],
        }
        with httpx.Client(base_url=BASE_URL) as client:
            resp = client.post("", json=body, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()

        results = []
        for group in data.get("results", []):
            series = group.get("data", [])
            if not series:
                continue
            latest = series[-1]["ratio"]
            earliest = series[0]["ratio"] or 1
            momentum = (latest - earliest) / earliest
            results.append(
                {
                    "keyword": group.get("title", ""),
                    "search_volume": latest,
                    "trend_momentum": momentum,
                }
            )
        return results
