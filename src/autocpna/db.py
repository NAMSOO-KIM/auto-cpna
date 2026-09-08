"""SQLAlchemy 엔진/세션 설정."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from autocpna.config import get_settings


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
    """모든 모델의 테이블을 생성. 최초 실행 시 1회 호출."""
    from autocpna.models import content_draft, product, publish_log  # noqa: F401

    Base.metadata.create_all(get_engine())
