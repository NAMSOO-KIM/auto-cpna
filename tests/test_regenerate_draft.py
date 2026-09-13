import pytest

from autocpna.db import get_session
from autocpna.models.content_draft import ContentDraft, ReviewStatus
from autocpna.models.product import Product
from autocpna.pipeline.orchestrator import regenerate_draft


def _make_rejected_draft(channel: str = "threads", reviewer_note: str = "") -> tuple[int, int]:
    with get_session() as session:
        product = Product(external_id="ext-1", name="상품", category="cat", price=1000)
        session.add(product)
        session.commit()
        session.refresh(product)

        draft = ContentDraft(
            product_id=product.id,
            channel=channel,
            caption_or_body="원래 본문",
            status=ReviewStatus.REJECTED,
            reviewer_note=reviewer_note,
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        return draft.id, product.id


def test_regenerate_passes_reviewer_note_as_feedback(fresh_db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    captured = {}

    def fake_generate(self, product, feedback=""):
        captured["product"] = product
        captured["feedback"] = feedback
        return "새로 생성된 본문"

    monkeypatch.setattr(
        "autocpna.content_gen.threads.ThreadsGenerator.generate", fake_generate
    )

    draft_id, product_id = _make_rejected_draft("threads", reviewer_note="가격을 더 강조해줘")
    new_draft = regenerate_draft(draft_id)

    assert captured["feedback"] == "가격을 더 강조해줘"
    assert new_draft.product_id == product_id
    assert new_draft.channel == "threads"
    assert new_draft.caption_or_body == "새로 생성된 본문"
    assert new_draft.status == ReviewStatus.PENDING

    with get_session() as session:
        old_draft = session.get(ContentDraft, draft_id)
        assert old_draft.status == ReviewStatus.REJECTED  # 이력 보존


def test_regenerate_raises_for_non_rejected_draft(fresh_db):
    with get_session() as session:
        product = Product(external_id="ext-2", name="상품", category="cat", price=1000)
        session.add(product)
        session.commit()
        session.refresh(product)

        draft = ContentDraft(
            product_id=product.id,
            channel="threads",
            caption_or_body="본문",
            status=ReviewStatus.PENDING,
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        draft_id = draft.id

    with pytest.raises(ValueError, match="is not rejected"):
        regenerate_draft(draft_id)


def test_regenerate_raises_for_missing_draft(fresh_db):
    with pytest.raises(ValueError, match="not found"):
        regenerate_draft(999999)
