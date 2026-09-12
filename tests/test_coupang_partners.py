import httpx
import pytest

from autocpna.ingestion.coupang_partners import CoupangPartnersClient


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

    monkeypatch.setattr("autocpna.ingestion._coupang_auth.httpx.Client", fake_client)

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

    monkeypatch.setattr("autocpna.ingestion._coupang_auth.httpx.Client", fake_client)

    with pytest.raises(RuntimeError, match="invalid keyword"):
        client.fetch(keyword="foo")
