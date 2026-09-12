"""쿠팡파트너스 오픈 API 커넥터.

인증 방식: HMAC-SHA256 서명 (쿠팡파트너스 오픈 API 공식 문서 기준).
"""
from __future__ import annotations

import hashlib
import hmac
import datetime as dt
from urllib.parse import urlencode

import httpx

from autocpna.config import get_scoring_weights, get_settings
from autocpna.ingestion.base import DataSource

BASE_URL = "https://api-gateway.coupang.com"
API_PREFIX = "/v2/providers/affiliate_open_api/apis/openapi/v1"


def _signed_date() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%y%m%dT%H%M%SZ")


def _generate_hmac_signature(
    method: str, path_with_query: str, secret_key: str, access_key: str, signed_date: str
) -> str:
    """쿠팡파트너스 API 요청 서명 생성 (공식 문서의 HMAC 알고리즘).

    서명 대상 메시지는 signed-date + method + path + querystring이다.
    쿼리스트링이 있는 요청(예: 상품 검색)에서 쿼리스트링을 빠뜨리면
    서명이 어긋나 항상 401을 반환하므로 path에는 반드시 쿼리스트링까지
    포함시켜야 한다.
    """
    message = signed_date + method + path_with_query
    signature = hmac.new(
        secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={access_key}, "
        f"signed-date={signed_date}, signature={signature}"
    )


class CoupangPartnersClient(DataSource):
    """상품 검색 커넥터.

    반환 dict 키: external_id, name, category, price, margin_rate,
    product_url, image_url (Product 모델과 매핑됨)

    주의: 쿠팡파트너스 상품 검색 API 응답에는 카테고리명/상품별 커미션율이
    포함되지 않는다 (커미션율은 카테고리별 고정 정책으로 파트너스
    대시보드에서만 확인 가능). 따라서 category는 검색 키워드로 대체하고,
    margin_rate는 config/scoring_weights.yaml의 default_margin_rate를 사용한다.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.access_key = settings.coupang_partners_access_key
        self.secret_key = settings.coupang_partners_secret_key
        self.vendor_id = settings.coupang_partners_vendor_id
        self.default_margin_rate = get_scoring_weights().get("default_margin_rate", 0.03)

    def _get(self, path: str, params: dict) -> dict:
        path_with_query = f"{path}?{urlencode(params)}" if params else path
        signed_date = _signed_date()
        headers = {
            "Authorization": _generate_hmac_signature(
                "GET", path_with_query, self.secret_key, self.access_key, signed_date
            ),
            "Content-Type": "application/json;charset=UTF-8",
        }
        with httpx.Client(base_url=BASE_URL) as client:
            resp = client.get(path_with_query, headers=headers)
            resp.raise_for_status()
            return resp.json()

    def fetch(self, keyword: str = "", limit: int = 20) -> list[dict]:
        """키워드 기반 상품 검색 (호출 제한: 분당 50회).

        응답 형식: {"rCode": "0", "rMessage": "", "data": {"productData": [...]}}
        """
        data = self._get(
            f"{API_PREFIX}/products/search", {"keyword": keyword, "limit": limit}
        )
        if str(data.get("rCode")) != "0":
            raise RuntimeError(f"쿠팡파트너스 API 오류: {data.get('rMessage')}")

        return [
            {
                "external_id": str(item.get("productId", "")),
                "name": item.get("productName", ""),
                "category": keyword,
                "price": float(item.get("productPrice", 0)),
                "margin_rate": self.default_margin_rate,
                "product_url": item.get("productUrl", ""),
                "image_url": item.get("productImage", ""),
            }
            for item in data.get("data", {}).get("productData", [])
        ]
