"""SQLAlchemy 엔진/세션 설정."""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from autocpna.config import get_settings

# Postgres 자문 잠금 키. 스키마 생성을 직렬화하는 용도로만 쓰는 임의의 상수.
_SCHEMA_LOCK_KEY = 8_241_119_407_233_001


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, echo=False)
    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


def init_db() -> None:
    """모든 모델의 테이블을 생성. 이미 있으면 아무것도 하지 않는다.

    Streamlit은 버튼을 누를 때마다 스크립트를 처음부터 다시 실행하므로 이
    함수도 반복 호출되고, 사용자가 여럿이면 동시에 호출된다. Postgres에서는
    빈 DB에 동시에 붙었을 때 create_all이 ReviewStatus ENUM 타입을 만드는
    구간에서 경합해 UniqueViolation(pg_type_typname_nsp_index)으로 죽는다 -
    checkfirst의 "확인 후 생성" 사이에 틈이 있기 때문이다. 자문 잠금으로
    한 번에 한 쪽만 생성하도록 직렬화한다(트랜잭션이 끝나면 자동 해제).
    sqlite는 단일 파일이라 이 경합이 없으므로 그대로 둔다.
    """
    from autocpna.models import content_draft, product, publish_log  # noqa: F401

    engine = get_engine()
    if engine.dialect.name != "postgresql":
        Base.metadata.create_all(engine)
        return

    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SCHEMA_LOCK_KEY})
        Base.metadata.create_all(conn)
