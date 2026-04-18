from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import db as app_db
from app.models import Base
from app.ingest import watcher as ingest_watcher
from app.routers import memory as memory_router
from app.wiki import worker as wiki_worker


@pytest.fixture()
def test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.db"
    fabric_dir = tmp_path / "fabric"
    fabric_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    SessionLocal = sessionmaker(engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE memory_fts USING fts5("
            "title, body, content='memory_entries', content_rowid='id',"
            " tokenize='porter unicode61')"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER memory_fts_ai AFTER INSERT ON memory_entries BEGIN "
            "INSERT INTO memory_fts(rowid, title, body) VALUES (new.id, new.title, new.body); END"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER memory_fts_ad AFTER DELETE ON memory_entries BEGIN "
            "INSERT INTO memory_fts(memory_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body); END"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER memory_fts_au AFTER UPDATE ON memory_entries BEGIN "
            "INSERT INTO memory_fts(memory_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body); "
            "INSERT INTO memory_fts(rowid, title, body) VALUES (new.id, new.title, new.body); END"
        )

    monkeypatch.setenv("FABRIC_DIR", str(fabric_dir))
    monkeypatch.setattr(app_db, "engine", engine)
    monkeypatch.setattr(app_db, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ingest_watcher, "SessionLocal", SessionLocal)
    monkeypatch.setattr(memory_router, "get_db", app_db.get_db)
    monkeypatch.setattr(wiki_worker, "SessionLocal", SessionLocal)

    try:
        yield {"db_path": db_path, "fabric_dir": fabric_dir, "engine": engine, "SessionLocal": SessionLocal}
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
