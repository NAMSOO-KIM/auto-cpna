"""검수 대시보드 (streamlit run dashboard/app.py).

목록 조회 + 이미지 미리보기 + 본문/해시태그 수정 + 승인/반려.
승인·반려 버튼을 누르면 화면에 입력된 수정 내용을 먼저 저장한 뒤 상태를 바꾼다.
"""
from __future__ import annotations

import streamlit as st

from autocpna.db import init_db
from autocpna.review import queue as review_queue

st.set_page_config(page_title="auto-cpna 검수", layout="wide")
init_db()

st.title("콘텐츠 검수 대기열")

pending = review_queue.list_pending()
if not pending:
    st.info("검수 대기 중인 초안이 없습니다.")

for draft in pending:
    with st.container(border=True):
        st.subheader(f"#{draft.id} · {draft.channel}")
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
            review_queue.approve(draft.id)
            st.rerun()

        if col3.button("반려", key=f"reject_{draft.id}"):
            review_queue.reject(draft.id)
            st.rerun()
