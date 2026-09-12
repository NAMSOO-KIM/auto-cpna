"""검수 대시보드 (streamlit run dashboard/app.py).

목록 조회(채널 필터 + 상품 컨텍스트) + 이미지 미리보기 + 본문/해시태그 수정
+ 승인/반려 + 최근 발행 로그.
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
from autocpna.review import queue as review_queue

st.set_page_config(page_title="auto-cpna 검수", layout="wide")
init_db()

st.title("콘텐츠 검수 대기열")

pending = review_queue.list_pending()

available_channels = sorted({d.channel for d in pending})
selected_channels = st.multiselect(
    "채널 필터", available_channels, default=available_channels
)
pending = [d for d in pending if d.channel in selected_channels]

if not pending:
    st.info("검수 대기 중인 초안이 없습니다.")

with get_session() as session:
    products_by_id = {
        draft.product_id: session.get(Product, draft.product_id) for draft in pending
    }

SOURCE_LABELS = {
    "coupang_partners": "쿠팡파트너스",
    "naver_shopping_connect": "네이버 쇼핑커넥트",
}

for draft in pending:
    product = products_by_id.get(draft.product_id)
    with st.container(border=True):
        st.subheader(f"#{draft.id} · {draft.channel}")
        if product:
            source_label = SOURCE_LABELS.get(product.source, product.source)
            st.caption(
                f"{product.name} · {product.category} · {product.price:,.0f}원 · "
                f"{source_label} · score={product.score:.3f}"
            )
        if draft.image_path:
            st.image(draft.image_path, width=300)

        body_key = f"body_{draft.id}"
        hashtags_key = f"hashtags_{draft.id}"
        st.text_area("본문", draft.caption_or_body, height=200, key=body_key)
        st.text_input("해시태그", draft.hashtags, key=hashtags_key)

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
            review_queue.reject(draft.id)
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
