"""최소 기능 검수 대시보드 (streamlit run dashboard/app.py).

목록 조회 + 이미지 미리보기 + 승인/반려만 지원. 편집 기능이 필요하면
review_queue에 update 함수를 추가해 확장.
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
        st.text_area("본문", draft.caption_or_body, height=200, key=f"body_{draft.id}")
        if draft.hashtags:
            st.caption(draft.hashtags)

        col1, col2, col3 = st.columns([1, 1, 3])
        if col1.button("승인", key=f"approve_{draft.id}"):
            review_queue.approve(draft.id)
            st.rerun()
        if col2.button("반려", key=f"reject_{draft.id}"):
            review_queue.reject(draft.id)
            st.rerun()
