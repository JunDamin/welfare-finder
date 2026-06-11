"""SQLite 정본(data/welfare.db) 스키마와 연결 헬퍼.

구조:
  services         목록 전체(welfare_full.json의 필드 그대로). kind로 중앙/지자체 구분.
  central_details  중앙부처 상세 (servId PK, 구조화 필드는 JSON 텍스트)
  local_details    지자체 상세 (동일 스키마)
  meta             key-value (collected_at 등)

원칙: DB가 파이프라인 정본이고, 사이트 서빙 JSON은 export_site.py가 DB에서 생성한다.
"""
import json
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB_PATH = BASE / "data" / "welfare.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
    serv_id      TEXT PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('central', 'local')),
    name         TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '[]',   -- JSON 배열
    themes       TEXT NOT NULL DEFAULT '[]',   -- JSON 배열
    benefit      TEXT NOT NULL DEFAULT '',
    how_to_apply TEXT NOT NULL DEFAULT '',
    agency       TEXT NOT NULL DEFAULT '',
    contact      TEXT NOT NULL DEFAULT '',
    source_url   TEXT NOT NULL DEFAULT '',
    confidence   TEXT NOT NULL DEFAULT '',
    online       INTEGER,                      -- 중앙만 0/1, 지자체 NULL
    cycle        TEXT NOT NULL DEFAULT '',
    provision    TEXT NOT NULL DEFAULT '',
    ministry     TEXT,                         -- 중앙만, 지자체 NULL
    region       TEXT,                         -- 지자체만, 중앙 NULL
    priority     INTEGER                       -- 중앙 상세 수집 우선순위(작을수록 먼저)
);

CREATE TABLE IF NOT EXISTS central_details (
    serv_id    TEXT PRIMARY KEY,
    target     TEXT NOT NULL DEFAULT '',
    criteria   TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL DEFAULT '',
    apply      TEXT NOT NULL DEFAULT '[]',     -- JSON 배열(문자열)
    forms      TEXT NOT NULL DEFAULT '[]',     -- JSON 배열({name, link})
    laws       TEXT NOT NULL DEFAULT '[]',     -- JSON 배열(문자열)
    contacts   TEXT NOT NULL DEFAULT '[]',     -- JSON 배열(문자열)
    homepages  TEXT NOT NULL DEFAULT '[]',     -- JSON 배열({name, link})
    fetched_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS local_details (
    serv_id    TEXT PRIMARY KEY,
    target     TEXT NOT NULL DEFAULT '',
    criteria   TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL DEFAULT '',
    apply      TEXT NOT NULL DEFAULT '[]',
    forms      TEXT NOT NULL DEFAULT '[]',
    laws       TEXT NOT NULL DEFAULT '[]',
    contacts   TEXT NOT NULL DEFAULT '[]',
    homepages  TEXT NOT NULL DEFAULT '[]',
    fetched_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DETAIL_FIELDS = ["target", "criteria", "content", "apply", "forms",
                 "laws", "contacts", "homepages"]
DETAIL_JSON_FIELDS = {"apply", "forms", "laws", "contacts", "homepages"}


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value))


def get_meta(con: sqlite3.Connection, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def insert_detail(con: sqlite3.Connection, table: str, serv_id: str,
                  detail: dict, fetched_at: str) -> None:
    """상세 dict({target, criteria, content, apply, forms, laws, contacts, homepages})
    를 INSERT(이미 있으면 갱신)."""
    assert table in ("central_details", "local_details")
    vals = []
    for f in DETAIL_FIELDS:
        v = detail.get(f)
        if f in DETAIL_JSON_FIELDS:
            vals.append(json.dumps(v or [], ensure_ascii=False))
        else:
            vals.append(v or "")
    con.execute(
        f"INSERT INTO {table} (serv_id, {', '.join(DETAIL_FIELDS)}, fetched_at) "
        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        f"ON CONFLICT(serv_id) DO UPDATE SET "
        + ", ".join(f"{f} = excluded.{f}" for f in DETAIL_FIELDS + ["fetched_at"]),
        [serv_id, *vals, fetched_at])


def detail_row_to_dict(row: sqlite3.Row) -> dict:
    d = {}
    for f in DETAIL_FIELDS:
        d[f] = json.loads(row[f]) if f in DETAIL_JSON_FIELDS else row[f]
    return d
