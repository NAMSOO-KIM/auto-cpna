from autocpna.content_gen.facebook import FacebookGenerator


def test_facebook_prompt_includes_product_details_and_disclosure(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    generator = FacebookGenerator()
    product = {
        "name": "무선 이어폰",
        "category": "이어폰",
        "price": 39000,
        "product_url": "https://example.com/product",
        "source": "coupang_partners",
    }

    prompt = generator.build_user_prompt(product)

    assert "무선 이어폰" in prompt
    assert "39000" in prompt
    assert "https://example.com/product" in prompt
    assert "쿠팡파트너스" in prompt


def test_facebook_prompt_uses_naver_disclosure_for_shopping_connect(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    generator = FacebookGenerator()
    product = {
        "name": "핸드크림",
        "category": "뷰티",
        "price": 15000,
        "product_url": "https://example.com/cream",
        "source": "naver_shopping_connect",
    }

    prompt = generator.build_user_prompt(product)

    assert "쇼핑커넥트" in prompt
    assert "쿠팡파트너스" not in prompt
