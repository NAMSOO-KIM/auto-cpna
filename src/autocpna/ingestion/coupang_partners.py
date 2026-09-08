"""쿠팡파트너스 오픈 API 커넥터.

인증 방식: HMAC-SHA256 서명 (쿠팡파트너스 오픈 API 공식 문서 기준).
서명 로직은 문서화된 표준 알고리즘이라 여기 구현되어 있지만,
실제 엔드포인트 응답 스키마는 계정 발급 후 실제 호출로 확인/보정 필요.
"""
from __future__ import annotations

import hashlib
import hmac
import datetime as dt

import httpx

from autocpna.config import get_settings
from autocpna.ingestion.base import DataSource

BASE_URL = "https://api-gateway.coupang.com"


def _generate_hmac_signature(method: str, url_path: str, secret_key: str, access_key: str) -> str:
    """쿠팡파트너스 API 요청 서명 생성 (공식 문서의 HMAC 알고리즘)."""
    datetime_str = dt.datetime.utcnow().strftime("%y%m%dT%H%M%SZ")
    message = datetime_str + method + url_path
    signature = hmac.new(
        secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={access_key}, "
        f"signed-date={datetime_str}, signature={signature}"
    )


class CoupangPartnersClient(DataSource):
    """상품 검색 / 딥링크 생성 커넥터.

    반환 dict 키: external_id, name, category, price, margin_rate,
    product_url, image_url (Product 모델과 매핑됨)
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.access_key = settings.coupang_partners_access_key
        self.secret_key = settings.coupang_partners_secret_key
        self.vendor_id = settings.coupang_partners_vendor_id

    def _headers(self, method: str, url_path: str) -> dict:
        return {
            "Authorization": _generate_hmac_signature(
                method, url_path, self.secret_key, self.access_key
            ),
            "Content-Type": "application/json",
        }

    def fetch(self, keyword: str = "", limit: int = 20) -> list[dict]:
        """키워드 기반 상품 검색.

        TODO: 실제 엔드포인트/응답 스키마는 쿠팡파트너스 API 문서 확정 후
        아래 url_path와 파싱 로직을 채워야 함. 현재는 골격만 존재.
        """
        url_path = "/v2/providers/affiliate_open_api/apis/openapi/products/search"
        params = {"keyword": keyword, "limit": limit}
        with httpx.Client(base_url=BASE_URL) as client:
            resp = client.get(
                url_path, params=params, headers=self._headers("GET", url_path)
            )
            resp.raise_for_status()
            data = resp.json()

        # TODO: 실제 응답 구조에 맞춰 매핑 보정 필요
        return [
            {
                "external_id": str(item.get("productId", "")),
                "name": item.get("productName", ""),
                "category": item.get("categoryName", ""),
                "price": float(item.get("productPrice", 0)),
                "margin_rate": float(item.get("commissionRate", 0)) / 100,
                "product_url": item.get("productUrl", ""),
                "image_url": item.get("productImage", ""),
            }
            for item in data.get("data", {}).get("productData", [])
        ]
