"""검수 대시보드 (streamlit run dashboard/app.py).

목록 조회(채널 필터 + 상품 컨텍스트) + 이미지 미리보기 + 본문/해시태그 수정
+ 승인/반려(사유 입력) + 반려 초안 재생성 + 최근 발행 로그.
승인·반려 버튼을 누르면 화면에 입력된 수정 내용을 먼저 저장한 뒤 상태를 바꾼다.
승인 시 채널이 requires_review=false면 review_queue.approve()가 자동으로
발행까지 트리거한다(channels.yaml 참고).
"""
from __future__ import annotations

import os

import streamlit as st

# Streamlit Community Cloud의 "Secrets"는 st.secrets로만 노출되고 일반
# 환경변수로는 자동 전달되지 않는다. config.py는 pydantic-settings로 os
# 환경변수/.env만 읽으므로, 배포 환경에서 설정한 Secrets를 여기서 미리
# os.environ에 복사해줘야 API 키들이 정상적으로 로드된다. 로컬 `streamlit
# run`(secrets.toml 없음)에서는 st.secrets 접근 자체가 예외를 던지므로 조용히
# 넘어간다.
try:
    for _key, _value in st.secrets.items():
        os.environ.setdefault(_key, str(_value))
except Exception:
    pass

from autocpna.db import get_session, init_db  # noqa: E402
from autocpna.models.content_draft import ReviewStatus  # noqa: E402
from autocpna.models.product import Product  # noqa: E402
from autocpna.models.publish_log import PublishLog  # noqa: E402
from autocpna.pipeline.orchestrator import (  # noqa: E402
    GENERATION_FAILURES,
    regenerate_draft,
)
from autocpna.review import queue as review_queue  # noqa: E402

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


_FLASH_KEY = "_flash_messages"


def flash(message: str, icon: str | None = None) -> None:
    """st.rerun() 이후에도 살아남는 안내 메시지를 예약한다.

    st.success/st.toast를 st.rerun() 직전에 호출하면 rerun이 스크립트를 처음부터
    다시 그리면서 그 메시지가 통째로 버려져, 저장/승인/재생성을 눌러도 사람은
    아무 확인 메시지를 못 본다. 그래서 session_state에 담아 두고 다음 렌더의
    맨 위에서 출력한다.
    """
    st.session_state.setdefault(_FLASH_KEY, []).append((message, icon))


st.title("콘텐츠 검수 대기열")

for _message, _icon in st.session_state.pop(_FLASH_KEY, []):
    st.toast(_message, icon=_icon)

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

        # Streamlit은 화면이 좁으면(폰) 컬럼을 세로로 쌓는다. 버튼을 기본
        # 크기로 두면 그때 54px짜리 작은 버튼 3개가 각각 한 줄씩 차지해서
        # 엄지로 누르기 불편하므로, width="stretch"로 각 칸을 꽉 채운다.
        # 데스크톱에서는 그대로 가로 3분할이라 레이아웃이 깨지지 않는다.
        col1, col2, col3 = st.columns(3)

        if col1.button("저장", key=f"save_{draft.id}", width="stretch"):
            review_queue.update_content(
                draft.id,
                caption_or_body=st.session_state[body_key],
                hashtags=st.session_state[hashtags_key],
            )
            flash("저장됨")
            st.rerun()

        if col2.button("승인", key=f"approve_{draft.id}", width="stretch", type="primary"):
            review_queue.update_content(
                draft.id,
                caption_or_body=st.session_state[body_key],
                hashtags=st.session_state[hashtags_key],
            )
            approved = review_queue.approve(draft.id)
            if approved.status == ReviewStatus.PUBLISHED:
                flash("승인 및 자동 발행 완료")
            elif review_queue.should_auto_publish(approved.channel):
                # 자동 발행 채널인데 여전히 APPROVED라는 건 발행이 시도됐지만
                # 실패했다는 뜻 (publish_approved_draft가 실패해도 상태를 그대로
                # 둔다) - "수동으로 트리거하세요"라고 하면 이미 시도했다가
                # 실패한 사실을 숨기게 되므로, PublishLog에서 실제 실패 사유를
                # 찾아 보여준다.
                with get_session() as session:
                    last_log = (
                        session.query(PublishLog)
                        .filter(PublishLog.draft_id == approved.id)
                        .order_by(PublishLog.published_at.desc())
                        .first()
                    )
                error_detail = f": {last_log.error_message}" if last_log else ""
                flash(f"승인됨, 자동 발행 시도했지만 실패{error_detail}", icon="⚠️")
            else:
                flash("승인됨 (발행은 별도로 트리거 필요)")
            st.rerun()

        if col3.button("반려", key=f"reject_{draft.id}", width="stretch"):
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

            if st.button("재생성", key=f"regenerate_{draft.id}", width="stretch"):
                # 재생성은 외부 API(Claude, 이미지 생성, Cloudinary)를 타므로
                # 실패가 정상적으로 발생한다. 그대로 두면 Streamlit이 화면에
                # 파이썬 트레이스백을 그려서 절대 경로까지 노출되므로, 운영상
                # 발생하는 실패는 사유만 보여준다(코드 버그는 그대로 터뜨림).
                try:
                    with st.spinner("반려 사유를 반영해 다시 생성 중..."):
                        new_draft = regenerate_draft(draft.id)
                except GENERATION_FAILURES as exc:
                    st.error(f"재생성 실패 ({type(exc).__name__}): {exc}")
                else:
                    flash(f"#{new_draft.id}로 재생성되어 검수 대기열에 추가됨")
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
