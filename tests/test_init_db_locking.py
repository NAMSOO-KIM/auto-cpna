"""init_db가 Postgres에서 스키마 생성을 직렬화하는지 확인.

Streamlit은 조작할 때마다 스크립트를 다시 실행하므로 init_db가 반복·동시
호출된다. 빈 Postgres DB에 동시에 붙으면 create_all이 ReviewStatus ENUM 타입을
만드는 구간에서 경합해 UniqueViolation(pg_type_typname_nsp_index)으로 죽었다.
실제 Postgres 16으로 재현/수정을 확인했고, 여기서는 잠금이 빠지는 회귀만 막는다.
"""
from contextlib import contextmanager
from types import SimpleNamespace

from autocpna import db


class _FakeConn:
    def __init__(self, statements):
        self.statements = statements

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))


class _FakeEngine:
    def __init__(self, dialect_name, statements):
        self.dialect = SimpleNamespace(name=dialect_name)
        self._statements = statements

    @contextmanager
    def begin(self):
        yield _FakeConn(self._statements)


def _run_init_db(monkeypatch, dialect_name):
    statements: list = []
    engine = _FakeEngine(dialect_name, statements)
    created_with: list = []

    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(
        db.Base.metadata, "create_all", lambda bind, **kw: created_with.append(bind)
    )
    db.init_db()
    return statements, created_with


def test_postgres_takes_advisory_lock_before_creating_schema(monkeypatch):
    statements, created_with = _run_init_db(monkeypatch, "postgresql")

    assert len(statements) == 1
    sql, params = statements[0]
    assert "pg_advisory_xact_lock" in sql
    assert params == {"key": db._SCHEMA_LOCK_KEY}
    # 잠금을 잡은 그 커넥션 위에서 생성해야 잠금이 의미가 있다.
    assert isinstance(created_with[0], _FakeConn)


def test_sqlite_creates_schema_without_locking(monkeypatch):
    statements, created_with = _run_init_db(monkeypatch, "sqlite")

    assert statements == []
    assert isinstance(created_with[0], _FakeEngine)
