"""검수 대시보드 (streamlit run dashboard/app.py).

목록 조회(채널 필터 + 상품 컨텍스트) + 이미지 미리보기 + 본문/해시태그 수정
+ 승인/반려(사유 입력) + 반려 초안 재생성 + 최근 발행 로그.
승인·반려 버튼을 누르면 화면에 입력된 수정 내용을 먼저 저장한 뒤 상태를 바꾼다.
승인 시 채널이 requires_review=false면 review_queue.approve()가 자동으로
발행까지 트리거한다(channels.yaml 참고).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

# 소스가 src/ 레이아웃이라 패키지를 설치하지 않으면 `import autocpna`가 안 된다.
# Streamlit Community Cloud는 requirements.txt의 의존성만 설치하고 저장소 자체를
# pip install 하지는 않으므로, 체크아웃만 된 상태에서도 임포트가 되도록 src를
# 직접 경로에 추가한다. 로컬에서 `pip install -e .`로 설치한 경우에는 이미
# 임포트가 되므로 이 줄이 동작을 바꾸지 않는다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

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
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from autocpna.config import get_channels_config, get_settings  # noqa: E402
from autocpna.pipeline.orchestrator import (  # noqa: E402
    GENERATION_FAILURES,
    generate_drafts,
    regenerate_draft,
    register_manual_product,
)
from autocpna.review import queue as review_queue  # noqa: E402

st.set_page_config(page_title="auto-cpna 검수", layout="wide")

try:
    init_db()
except (OperationalError, ModuleNotFoundError) as exc:
    # DATABASE_URL을 새로 붙이는 시점에 가장 흔하게 터지는 지점인데, 배포
    # 환경에서는 트레이스백을 숨기도록 해놔서(.streamlit/config.toml) 그대로
    # 두면 화면에 예외 종류만 뜨고 원인을 알 수 없다. 흔한 원인을 같이 안내한다.
    # DB URL은 비밀번호가 들어 있으므로 화면에 찍지 않는다.
    st.error(
        "데이터베이스에 연결하지 못했습니다.\n\n"
        "자주 발생하는 원인:\n"
        "- Supabase의 Direct connection(db.xxx.supabase.co) 사용 "
        "→ IPv6 전용이라 실패합니다. Session pooler 주소(pooler.supabase.com:5432)를 쓰세요.\n"
        "- 비밀번호의 특수문자(@ : / # 등)를 URL 인코딩하지 않음 "
        "→ @는 %40, #은 %23 으로 바꿔야 합니다.\n"
        "- 비밀번호에 `[YOUR-PASSWORD]` 자리표시자가 그대로 남아 있음\n"
        "- Postgres 드라이버 미설치 → `pip install -r requirements.txt`\n\n"
        f"드라이버 메시지: {type(exc).__name__}"
    )
    st.stop()

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


def _database_status() -> tuple[str, bool]:
    """(표시용 DB 위치, 영구 저장 여부). 비밀번호가 화면에 찍히지 않도록
    URL에서 스킴과 호스트만 뽑아 쓴다."""
    url = make_url(get_settings().database_url)
    backend = url.get_backend_name()
    if backend == "sqlite":
        return f"sqlite ({url.database})", False
    return f"{backend} @ {url.host}", True


st.title("콘텐츠 검수 대기열")

_db_label, _db_persistent = _database_status()
if _db_persistent:
    st.caption(f"DB: {_db_label}")
else:
    # Streamlit Community Cloud는 컨테이너 파일시스템이 재시작마다 초기화된다.
    # sqlite로 돌고 있으면 검수 대기 중이던 초안이 예고 없이 사라지므로 알린다.
    st.warning(
        f"DB: {_db_label} — 재시작 시 초기화됩니다. 배포 환경에서 계속 쓰시려면 "
        "Secrets에 `DATABASE_URL`(Postgres)을 설정하세요.",
        icon="⚠️",
    )

for _message, _icon in st.session_state.pop(_FLASH_KEY, []):
    st.toast(_message, icon=_icon)

with st.expander("➕ 새 상품 등록하고 초안 생성", expanded=False):
    st.caption(
        "배포된 대시보드에서는 CLI(autocpna add-product / generate)를 쓸 수 없으므로, "
        "상품 등록부터 초안 생성까지 여기서 처리한다. 링크와 수수료율은 제휴 사이트에서 "
        "직접 확인한 값을 넣을 것."
    )
    enabled_channels = [c for c, cfg in get_channels_config().items() if cfg.get("enabled")]

    with st.form("new_product"):
        name = st.text_input("상품명")
        category = st.text_input("카테고리")
        price = st.number_input("가격(원)", min_value=0, step=1000, value=0)
        product_url = st.text_input("상품 링크 (제휴 링크)")
        margin_rate = st.number_input(
            "수수료율", min_value=0.0, max_value=1.0, step=0.01, value=0.03,
            help="0.03 = 3%",
        )
        source = st.selectbox(
            "제휴 프로그램",
            list(SOURCE_LABELS),
            format_func=lambda s: SOURCE_LABELS[s],
            help="콘텐츠에 들어갈 제휴 고지 문구가 이 값에 따라 달라진다",
        )
        keyword = st.text_input("트렌드 조회 키워드 (선택)")
        channels = st.multiselect("생성할 채널", enabled_channels, default=enabled_channels)
        submitted = st.form_submit_button("등록하고 초안 생성", width="stretch", type="primary")

    if submitted:
        if not (name and category and product_url):
            st.error("상품명 / 카테고리 / 상품 링크는 필수입니다.")
        elif price <= 0:
            # 0원으로 두면 생성기가 가격을 못 쓰고 "가격 정보가 없다"고 에두르는
            # 본문이 나온다(추측 금지 규칙). 호출 비용만 쓰고 버리게 되므로 막는다.
            st.error("가격을 입력하세요. 0원이면 가격을 뺀 어정쩡한 본문이 생성됩니다.")
        else:
            with st.spinner("상품 등록 후 채널별 초안 생성 중..."):
                product = register_manual_product(
                    name=name,
                    category=category,
                    price=float(price),
                    product_url=product_url,
                    margin_rate=float(margin_rate),
                    source=source,
                    keyword=keyword,
                )
                result = generate_drafts(product, channels=channels or None)
            for channel, reason in result.failures.items():
                st.warning(f"[{channel}] 생성 실패: {reason}")
            flash(f"상품 #{product.id} 등록, 초안 {len(result.drafts)}개 생성됨")
            if not result.failures:
                st.rerun()

st.divider()

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
