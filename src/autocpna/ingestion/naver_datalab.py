"""네이버 데이터랩 (검색어 트렌드) API 커넥터.

주의(2026-09 기준): 네이버는 검색어 트렌드/쇼핑인사이트 API를 기존
개발자센터(openapi.naver.com, X-Naver-Client-Id/Secret)에서 NAVER Cloud
Platform의 NAVER API HUB(naverapihub.apigw.ntruss.com,
X-NCP-APIGW-API-KEY-ID/-KEY)로 이관했다. 신규 발급은 API HUB에서만
가능하므로 이 커넥터는 API HUB 엔드포인트를 기본으로 사용한다.
이관 신청을 마친 기존 개발자센터 키는 유예기간 동안 구 엔드포인트로도
호출 가능하다고 안내되어 있어, 필요 시 use_legacy_endpoint=True로 전환할 수
있게 해 두었다. 요청/응답 바디 포맷(keywordGroups, results[].data[].ratio 등)은
이관 전후로 동일하다.
"""
from __future__ import annotations

import datetime as dt

import httpx

from autocpna.config import get_settings
from autocpna.ingestion.base import DataSource

HUB_URL = "https://naverapihub.apigw.ntruss.com/search-trend/v1/search"
LEGACY_URL = "https://openapi.naver.com/v1/datalab/search"

MAX_KEYWORD_GROUPS = 5


def _months_ago(months: int, from_date: dt.date | None = None) -> dt.date:
    today = from_date or dt.date.today()
    year, month = today.year, today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return dt.date(year, month, 1)


class NaverDatalabClient(DataSource):
    """키워드별 검색량 추세를 반환.

    반환 dict 키: keyword, search_volume(상대 지수), trend_momentum(최근 대비 증감률)
    """

    def __init__(self, use_legacy_endpoint: bool = False) -> None:
        settings = get_settings()
        self.client_id = settings.naver_datalab_client_id
        self.client_secret = settings.naver_datalab_client_secret
        self.use_legacy_endpoint = use_legacy_endpoint

    def _url_and_headers(self) -> tuple[str, dict]:
        if self.use_legacy_endpoint:
            return LEGACY_URL, {
                "X-Naver-Client-Id": self.client_id,
                "X-Naver-Client-Secret": self.client_secret,
                "Content-Type": "application/json",
            }
        return HUB_URL, {
            "X-NCP-APIGW-API-KEY-ID": self.client_id,
            "X-NCP-APIGW-API-KEY": self.client_secret,
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

        keywordGroups는 요청당 최대 5개까지만 허용되므로 초과분은 잘라서 보낸다
        (서버가 초과 요청을 400으로 거부하므로). ratio는 요청 구간 내 최댓값을
        100으로 둔 상대값이라 서로 다른 요청 결과끼리는 비교할 수 없다(같은 요청
        안에서만 비교 가능).
        """
        keywords = (keywords or [])[:MAX_KEYWORD_GROUPS]
        data = self._post(keywords, start_date, end_date, time_unit)

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

    def fetch_monthly_series(self, keyword: str, months: int = 24) -> dict[str, str | float]:
        """최근 `months`개월치 월별 검색 트렌드 원본 시계열을 {"YYYY-MM": ratio}로 반환.

        scoring.normalize.compute_seasonality_fit의 입력으로 쓰인다 (정규화는
        여기서 하지 않고 스코어링 계층에서 처리 - 다른 ingestion 결과와 동일한
        관례).
        """
        start = _months_ago(months)
        end = dt.date.today()
        data = self._post([keyword], start.isoformat(), end.isoformat(), "month")

        results = data.get("results", [])
        if not results:
            return {}
        return {point["period"][:7]: point["ratio"] for point in results[0].get("data", [])}

    def _post(self, keywords: list[str], start_date: str, end_date: str, time_unit: str) -> dict:
        body = {
            "startDate": start_date,
            "endDate": end_date,
            "timeUnit": time_unit,
            "keywordGroups": [{"groupName": kw, "keywords": [kw]} for kw in keywords],
        }
        url, headers = self._url_and_headers()
        with httpx.Client() as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()
