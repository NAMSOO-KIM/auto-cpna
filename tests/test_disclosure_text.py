from autocpna.content_gen.instagram import InstagramGenerator
from autocpna.content_gen.threads import ThreadsGenerator


def test_coupang_partners_product_gets_coupang_disclosure(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    generator = InstagramGenerator()

    text = generator.disclosure_text({"source": "coupang_partners"})

    assert "쿠팡파트너스" in text
    assert "네이버" not in text


def test_naver_shopping_connect_product_gets_naver_disclosure(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    generator = ThreadsGenerator()

    text = generator.disclosure_text({"source": "naver_shopping_connect"})

    assert "쇼핑커넥트" in text
    assert "쿠팡" not in text


def test_missing_source_falls_back_to_coupang_disclosure(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    generator = InstagramGenerator()

    assert generator.disclosure_text({}) == generator.disclosure_text({"source": "coupang_partners"})


def test_instagram_prompt_embeds_correct_disclosure(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    generator = InstagramGenerator()
    product = {
        "name": "무선 이어폰",
        "category": "이어폰",
        "price": 39000,
        "product_url": "https://example.com",
        "source": "naver_shopping_connect",
    }

    prompt = generator.build_user_prompt(product)

    assert "쇼핑커넥트" in prompt
    assert "쿠팡파트너스" not in prompt


def test_feedback_block_empty_when_no_feedback(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    generator = InstagramGenerator()

    assert generator.feedback_block("") == ""


def test_feedback_block_included_in_prompt_when_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    generator = InstagramGenerator()
    product = {
        "name": "무선 이어폰",
        "category": "이어폰",
        "price": 39000,
        "product_url": "https://example.com",
        "source": "coupang_partners",
    }

    prompt = generator.build_user_prompt(product, feedback="너무 과장됐어, 톤 낮춰줘")

    assert "너무 과장됐어, 톤 낮춰줘" in prompt
