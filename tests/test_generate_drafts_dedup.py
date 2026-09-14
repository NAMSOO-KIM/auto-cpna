"""generate_drafts를 반복 호출해도(예: autocpna generate를 매일 실행) 이미
검수 대기/승인/발행 상태인 (product, channel) 조합에는 초안을 다시 만들지
않는지 확인."""
from autocpna.db import get_session
from autocpna.models.content_draft import ContentDraft, ReviewStatus
from autocpna.models.product import Product
from autocpna.pipeline.orchestrator import generate_drafts


def _make_product(fresh_db) -> Product:
    with get_session() as session:
        product = Product(external_id="ext-1", name="상품", category="cat", price=1000)
        session.add(product)
        session.commit()
        session.refresh(product)
        return product


def test_second_call_skips_channel_with_pending_draft(fresh_db, monkeypatch):
    monkeypatch.setattr(
        "autocpna.content_gen.threads.ThreadsGenerator.generate",
        lambda self, product, feedback="": "본문",
    )
    product = _make_product(fresh_db)

    first_drafts = generate_drafts(product, channels=["threads"])
    assert len(first_drafts) == 1

    second_drafts = generate_drafts(product, channels=["threads"])
    assert second_drafts == []

    with get_session() as session:
        count = (
            session.query(ContentDraft)
            .filter(ContentDraft.product_id == product.id, ContentDraft.channel == "threads")
            .count()
        )
        assert count == 1


def test_rejected_draft_does_not_block_new_generation(fresh_db, monkeypatch):
    monkeypatch.setattr(
        "autocpna.content_gen.threads.ThreadsGenerator.generate",
        lambda self, product, feedback="": "본문",
    )
    product = _make_product(fresh_db)

    [first_draft] = generate_drafts(product, channels=["threads"])
    with get_session() as session:
        draft = session.get(ContentDraft, first_draft.id)
        draft.status = ReviewStatus.REJECTED
        session.commit()

    second_drafts = generate_drafts(product, channels=["threads"])
    assert len(second_drafts) == 1


def test_only_missing_channel_is_generated(fresh_db, monkeypatch):
    monkeypatch.setattr(
        "autocpna.content_gen.threads.ThreadsGenerator.generate",
        lambda self, product, feedback="": "스레드 본문",
    )
    monkeypatch.setattr(
        "autocpna.content_gen.facebook.FacebookGenerator.generate",
        lambda self, product, feedback="": "페북 본문",
    )
    product = _make_product(fresh_db)

    generate_drafts(product, channels=["threads"])
    second_drafts = generate_drafts(product, channels=["threads", "facebook"])

    assert len(second_drafts) == 1
    assert second_drafts[0].channel == "facebook"
