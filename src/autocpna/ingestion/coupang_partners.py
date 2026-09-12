"""쿠팡파트너스 오픈 API 상품 검색 커넥터."""
from __future__ import annotations

from autocpna.config import get_scoring_weights, get_settings
from autocpna.ingestion._coupang_auth import API_PREFIX, authenticated_get
from autocpna.ingestion.base import DataSource


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

    def fetch(self, keyword: str = "", limit: int = 20) -> list[dict]:
        """키워드 기반 상품 검색 (호출 제한: 분당 50회).

        응답 형식: {"rCode": "0", "rMessage": "", "data": {"productData": [...]}}
        """
        data = authenticated_get(
            f"{API_PREFIX}/products/search",
            {"keyword": keyword, "limit": limit},
            self.access_key,
            self.secret_key,
        )
        if str(data.get("rCode")) != "0":
            raise RuntimeError(f"쿠팡파트너스 API 오류: {data.get('rMessage')}")

        return [
            {
                "external_id": str(item.get("productId", "")),
                "source": "coupang_partners",
                "name": item.get("productName", ""),
                "category": keyword,
                "price": float(item.get("productPrice", 0)),
                "margin_rate": self.default_margin_rate,
                "product_url": item.get("productUrl", ""),
                "image_url": item.get("productImage", ""),
            }
            for item in data.get("data", {}).get("productData", [])
        ]
