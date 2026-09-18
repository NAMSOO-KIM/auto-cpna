"""생성 요청이 실제로 어떤 model/max_tokens로 나가는지 확인.

블로그 비교글(generate_comparison)은 예전에 자체 messages.create 호출을 들고
있어서 본문 상한이 따로 관리됐다 - 공용 경로(complete)로 합쳐졌는지까지 검증한다.
"""
from types import SimpleNamespace

from autocpna.content_gen.base import MAX_TOKENS, MODEL
from autocpna.content_gen.blog import BlogGenerator
from autocpna.content_gen.instagram import InstagramGenerator

PRODUCT = {
    "name": "무선 이어폰",
    "category": "이어폰",
    "price": 39000,
    "product_url": "https://example.com",
    "source": "coupang_partners",
}


def _capture_create(generator, captured):
    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="본문")], stop_reason="end_turn"
        )

    generator._client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))


def test_generate_uses_current_model_and_max_tokens(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    generator = InstagramGenerator()
    captured = {}
    _capture_create(generator, captured)

    assert generator.generate(PRODUCT) == "본문"
    assert captured["model"] == MODEL
    assert captured["max_tokens"] == MAX_TOKENS


def test_blog_comparison_goes_through_shared_complete(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    generator = BlogGenerator()
    captured = {}
    _capture_create(generator, captured)

    assert generator.generate_comparison("무선 이어폰", [PRODUCT]) == "본문"
    assert captured["max_tokens"] == MAX_TOKENS  # 예전엔 2048로 따로 박혀 있었음


def test_blog_prompt_length_request_fits_in_max_tokens(monkeypatch):
    """프롬프트가 요구하는 분량이 상한 안에 들어오는지.

    한국어는 글자수보다 토큰수가 많고(대략 1~1.5배), 적응형 사고가 켜진 모델은
    사고 토큰도 같은 max_tokens에서 쓴다. 그래서 본문 토큰 추정치만이 아니라
    사고 몫까지 감안한 배수로 여유를 확인한다.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    generator = BlogGenerator()

    requested_chars = 2200  # 비교글 프롬프트의 상한
    body_tokens = requested_chars * 1.5
    assert MAX_TOKENS > body_tokens * 4  # 본문 외에 사고 몫까지

    assert "2200자" in generator.build_comparison_prompt("무선 이어폰", [PRODUCT])
