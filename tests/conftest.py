import pytest


@pytest.fixture
def fresh_db(monkeypatch, tmp_path):
    """실제 DB 접근이 필요한 테스트용 격리된 sqlite 파일 DB.

    autocpna.db는 엔진/세션팩토리를 모듈 전역으로 캐싱하므로, 테스트마다
    DATABASE_URL을 바꾸는 것만으로는 반영되지 않는다 - 캐시된 전역도 함께
    리셋해야 매 테스트가 독립된 DB를 쓴다.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    from autocpna.config import get_settings
    from autocpna import db

    get_settings.cache_clear()
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_SessionLocal", None)
    db.init_db()
