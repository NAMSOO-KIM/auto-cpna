"""검수 대시보드 (streamlit run dashboard/app.py).

목록 조회(채널 필터 + 상품 컨텍스트) + 이미지 미리보기 + 본문/해시태그 수정
+ 승인/반려(사유 입력) + 반려 초안 재생성 + 최근 발행 로그.
승인·반려 버튼을 누르면 화면에 입력된 수정 내용을 먼저 저장한 뒤 상태를 바꾼다.
승인 시 채널이 requires_review=false면 review_queue.approve()가 자동으로
발행까지 트리거한다(channels.yaml 참고).
"""
from __future__ import annotations

import streamlit as st

from autocpna.db import get_session, init_db
from autocpna.models.content_draft import ReviewStatus
from autocpna.models.product import Product
from autocpna.models.publish_log import PublishLog
from autocpna.pipeline.orchestrator import regenerate_draft
from autocpna.review import queue as review_queue

st.set_page_config(page_title="auto-cpna 검수", layout="wide")
init_db()

SOURCE_LABELS = {
    "coupang_partners": "쿠팡파트너스",
    "naver_shopping_connect": "네이버 쇼핑커넥트",
}


def _load_products(drafts) -> dict:
    with get_session() as session:
        return {d.product_id: session.get(Product, d.product_id) for d in drafts}


def _product_caption(product) -> str:
    source_label = SOURCE_LABELS.get(product.source, product.source)
    return (
        f"{product.name} · {product.category} · {product.price:,.0f}원 · "
        f"{source_label} · score={product.score:.3f}"
    )


st.title("콘텐츠 검수 대기열")

pending = review_queue.list_pending()

available_channels = sorted({d.channel for d in pending})
selected_channels = st.multiselect(
    "채널 필터", available_channels, default=available_channels
)
pending = [d for d in pending if d.channel in selected_channels]

if not pending:
    st.info("검수 대기 중인 초안이 없습니다.")

products_by_id = _load_products(pending)

for draft in pending:
    product = products_by_id.get(draft.product_id)
    with st.container(border=True):
        st.subheader(f"#{draft.id} · {draft.channel}")
        if product:
            st.caption(_product_caption(product))
        if draft.image_path:
            st.image(draft.image_path, width=300)

        body_key = f"body_{draft.id}"
        hashtags_key = f"hashtags_{draft.id}"
        reject_note_key = f"reject_note_{draft.id}"
        st.text_area("본문", draft.caption_or_body, height=200, key=body_key)
        st.text_input("해시태그", draft.hashtags, key=hashtags_key)
        st.text_input("반려 사유 (반려 시 입력, 재생성에 반영됨)", key=reject_note_key)

        col1, col2, col3, col4 = st.columns([1, 1, 1, 2])

        if col1.button("저장", key=f"save_{draft.id}"):
            review_queue.update_content(
                draft.id,
                caption_or_body=st.session_state[body_key],
                hashtags=st.session_state[hashtags_key],
            )
            st.success("저장됨")
            st.rerun()

        if col2.button("승인", key=f"approve_{draft.id}"):
            review_queue.update_content(
                draft.id,
                caption_or_body=st.session_state[body_key],
                hashtags=st.session_state[hashtags_key],
            )
            approved = review_queue.approve(draft.id)
            if approved.status == ReviewStatus.PUBLISHED:
                st.success("승인 및 자동 발행 완료")
            else:
                st.success("승인됨 (발행은 별도로 트리거 필요)")
            st.rerun()

        if col3.button("반려", key=f"reject_{draft.id}"):
            review_queue.reject(draft.id, note=st.session_state[reject_note_key])
            st.rerun()

st.divider()
st.subheader("반려된 초안 (재생성 가능)")

rejected = review_queue.list_rejected()
if not rejected:
    st.caption("반려된 초안이 없습니다.")
else:
    rejected_products = _load_products(rejected)
    for draft in rejected:
        product = rejected_products.get(draft.product_id)
        with st.container(border=True):
            st.write(f"#{draft.id} · {draft.channel}")
            if product:
                st.caption(_product_caption(product))
            if draft.reviewer_note:
                st.caption(f"반려 사유: {draft.reviewer_note}")
            st.text(draft.caption_or_body[:200] + ("..." if len(draft.caption_or_body) > 200 else ""))

            if st.button("재생성", key=f"regenerate_{draft.id}"):
                with st.spinner("반려 사유를 반영해 다시 생성 중..."):
                    new_draft = regenerate_draft(draft.id)
                st.success(f"#{new_draft.id}로 재생성되어 검수 대기열에 추가됨")
                st.rerun()

st.divider()
st.subheader("최근 발행 로그")

with get_session() as session:
    recent_logs = (
        session.query(PublishLog).order_by(PublishLog.published_at.desc()).limit(20).all()
    )

if not recent_logs:
    st.caption("발행 기록이 없습니다.")
else:
    for log in recent_logs:
        timestamp = log.published_at.strftime("%Y-%m-%d %H:%M")
        if log.success:
            st.write(f"✅ #{log.draft_id} [{log.channel}] {timestamp} · post_id={log.remote_post_id}")
        else:
            st.write(f"❌ #{log.draft_id} [{log.channel}] {timestamp} · {log.error_message}")
