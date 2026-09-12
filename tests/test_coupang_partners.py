import hashlib
import hmac

import httpx
import pytest

from autocpna.ingestion.coupang_partners import CoupangPartnersClient, _generate_hmac_signature


def test_signature_message_includes_query_string():
    """서명 대상 메시지에 쿼리스트링이 빠지면 실제 API가 401을 반환하므로
    쿼리스트링을 포함한 path로 서명했을 때만 검증에 성공해야 한다."""
    secret_key = "test-secret"
    access_key = "test-access"
    signed_date = "250101T000000Z"
    path_with_query = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search?keyword=foo&limit=5"

    header = _generate_hmac_signature("GET", path_with_query, secret_key, access_key, signed_date)

    expected_message = signed_date + "GET" + path_with_query
    expected_signature = hmac.new(
        secret_key.encode("utf-8"), expected_message.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    assert f"signature={expected_signature}" in header
    assert f"access-key={access_key}" in header
    assert f"signed-date={signed_date}" in header


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COUPANG_PARTNERS_ACCESS_KEY", "access")
    monkeypatch.setenv("COUPANG_PARTNERS_SECRET_KEY", "secret")
    from autocpna.config import get_settings, get_scoring_weights

    get_settings.cache_clear()
    get_scoring_weights.cache_clear()
    return CoupangPartnersClient()


def test_fetch_parses_official_response_schema(client, monkeypatch):
    """공식 문서 예시 응답 스키마(productData 배열, productPrice 등)를 그대로 파싱하는지 검증."""
    captured_request = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request["url"] = str(request.url)
        captured_request["authorization"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "rCode": "0",
                "rMessage": "",
                "data": {
                    "landingUrl": "https://link.coupang.com/re/AFFSRP?pageKey=x",
                    "productData": [
                        {
                            "keyword": "아이폰",
                            "rank": 1,
                            "isRocket": True,
                            "isFreeShipping": False,
                            "productId": 27664441,
                            "productImage": "https://ads-partners.coupang.com/image1/foo.jpg",
                            "productName": "Apple 아이폰 15 Pro 256GB",
                            "productPrice": 1550000,
                            "productUrl": "https://link.coupang.com/re/AFFSDP?itemId=1",
                        }
                    ],
                },
            },
        )

    real_client_cls = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client_cls(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("autocpna.ingestion.coupang_partners.httpx.Client", fake_client)

    products = client.fetch(keyword="아이폰", limit=5)

    assert len(products) == 1
    product = products[0]
    assert product["external_id"] == "27664441"
    assert product["name"] == "Apple 아이폰 15 Pro 256GB"
    assert product["category"] == "아이폰"
    assert product["price"] == 1550000.0
    assert product["margin_rate"] == client.default_margin_rate
    assert product["product_url"] == "https://link.coupang.com/re/AFFSDP?itemId=1"
    assert product["image_url"] == "https://ads-partners.coupang.com/image1/foo.jpg"

    assert "keyword=" in captured_request["url"]
    assert "limit=5" in captured_request["url"]
    assert captured_request["authorization"].startswith("CEA algorithm=HmacSHA256")


def test_fetch_raises_on_error_rcode(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rCode": "400001", "rMessage": "invalid keyword"})

    real_client_cls = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client_cls(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("autocpna.ingestion.coupang_partners.httpx.Client", fake_client)

    with pytest.raises(RuntimeError, match="invalid keyword"):
        client.fetch(keyword="foo")
