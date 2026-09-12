"""쿠팡파트너스 커미션 리포트 API 커넥터.

일별 클릭수/주문수/GMV/커미션 집계를 제공하며, 이를 이용해 계정 전체의
실측 전환율(주문수/클릭수)을 계산할 수 있다. 상품/카테고리 단위가 아니라
계정 전체 집계이므로 카테고리별 전환율의 대체값이 아니라, 스코어링 엔진의
config 상 고정값(default_conversion_rate)을 대체하는 "실측 평균값"으로 쓴다.

응답 형식: {"rCode": "0", "rMessage": "", "data": [{"date", "clickCount",
"orderCount", "gmv", "commission"}, ...]}
호출 제한: 시간당 500회.
"""
from __future__ import annotations

from autocpna.config import get_settings
from autocpna.ingestion._coupang_auth import API_PREFIX, authenticated_get
from autocpna.ingestion.base import DataSource

MAX_PAGES = 50


class CoupangReportsClient(DataSource):
    def __init__(self) -> None:
        settings = get_settings()
        self.access_key = settings.coupang_partners_access_key
        self.secret_key = settings.coupang_partners_secret_key

    def fetch(self, start_date: str = "", end_date: str = "") -> list[dict]:
        """start_date/end_date는 YYYYMMDD 형식. 일별 커미션 리포트 행을 모두 모아 반환."""
        rows: list[dict] = []
        page = 0
        while page < MAX_PAGES:
            data = authenticated_get(
                f"{API_PREFIX}/reports/commission",
                {"startDate": start_date, "endDate": end_date, "page": page},
                self.access_key,
                self.secret_key,
            )
            if str(data.get("rCode")) != "0":
                raise RuntimeError(f"쿠팡파트너스 리포트 API 오류: {data.get('rMessage')}")
            page_rows = data.get("data") or []
            if not page_rows:
                break
            rows.extend(page_rows)
            page += 1
        return rows

    def conversion_rate(self, start_date: str, end_date: str) -> float | None:
        """구간 내 계정 전체 전환율(총 주문수/총 클릭수). 클릭이 전혀 없으면 None."""
        rows = self.fetch(start_date, end_date)
        total_clicks = sum(row.get("clickCount", 0) for row in rows)
        total_orders = sum(row.get("orderCount", 0) for row in rows)
        if total_clicks <= 0:
            return None
        return total_orders / total_clicks
