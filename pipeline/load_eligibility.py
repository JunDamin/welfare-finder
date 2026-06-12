"""merged.json(추출 결과 1,079건)을 welfare.db에 적재.

테이블 신설/갱신:
  eligibility   (servId PK + 소득/연령/카테고리/배제/요약/신뢰도)
  req_documents (servId × 서류 다대다; std_name/raw_name/kind/source)

멱등: servId 기준 upsert. req_documents는 servId 단위로 전량 교체(delete+insert).
선행: standardize_docs.py 가 먼저 실행되어 documents[].std_name 이 채워져 있어야 함.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402

BASE = db.BASE
MERGED = BASE / "_ext" / "merged.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS eligibility (
    serv_id             TEXT PRIMARY KEY,
    income_type         TEXT,
    income_pct          REAL,
    income_bound        TEXT,
    income_raw          TEXT NOT NULL DEFAULT '',
    income_conf         TEXT NOT NULL DEFAULT '',
    age_min             INTEGER,
    age_max             INTEGER,
    age_unit            TEXT,
    age_raw             TEXT NOT NULL DEFAULT '',
    age_conf            TEXT NOT NULL DEFAULT '',
    req_categories      TEXT NOT NULL DEFAULT '[]',  -- JSON 배열({cat, raw})
    exclusions          TEXT NOT NULL DEFAULT '[]',  -- JSON 배열({what, raw})
    eligibility_summary TEXT NOT NULL DEFAULT '',
    doc_summary         TEXT NOT NULL DEFAULT '',
    overall_conf        TEXT NOT NULL DEFAULT '',
    notes               TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS req_documents (
    serv_id   TEXT NOT NULL,
    std_name  TEXT NOT NULL DEFAULT '',
    raw_name  TEXT NOT NULL DEFAULT '',
    kind      TEXT NOT NULL DEFAULT '',
    source    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_reqdoc_serv ON req_documents(serv_id);
CREATE INDEX IF NOT EXISTS idx_reqdoc_std  ON req_documents(std_name);
"""


def upsert_eligibility(con, it):
    sid = it["servId"]
    inc = it.get("income") or {}
    age = it.get("age") or {}
    con.execute(
        "INSERT INTO eligibility (serv_id, income_type, income_pct, income_bound, "
        "income_raw, income_conf, age_min, age_max, age_unit, age_raw, age_conf, "
        "req_categories, exclusions, eligibility_summary, doc_summary, overall_conf, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(serv_id) DO UPDATE SET "
        + ", ".join(
            f"{c} = excluded.{c}" for c in (
                "income_type", "income_pct", "income_bound", "income_raw",
                "income_conf", "age_min", "age_max", "age_unit", "age_raw",
                "age_conf", "req_categories", "exclusions", "eligibility_summary",
                "doc_summary", "overall_conf", "notes")
        ),
        (
            sid,
            inc.get("type"), inc.get("median_pct"), inc.get("bound"),
            inc.get("raw") or "", inc.get("confidence") or "",
            age.get("min"), age.get("max"), age.get("unit"),
            age.get("raw") or "", age.get("confidence") or "",
            json.dumps(it.get("required_categories") or [], ensure_ascii=False),
            json.dumps(it.get("exclusions") or [], ensure_ascii=False),
            it.get("eligibility_summary") or "",
            it.get("doc_summary") or "",
            it.get("overall_confidence") or "",
            it.get("notes") or "",
        ),
    )


def replace_documents(con, it):
    sid = it["servId"]
    con.execute("DELETE FROM req_documents WHERE serv_id = ?", (sid,))
    for doc in it.get("documents") or []:
        con.execute(
            "INSERT INTO req_documents (serv_id, std_name, raw_name, kind, source) "
            "VALUES (?,?,?,?,?)",
            (sid,
             doc.get("std_name") or doc.get("name") or "",
             doc.get("name") or "",
             doc.get("kind") or "",
             doc.get("source") or ""),
        )


def main():
    con = db.connect()
    con.executescript(SCHEMA)

    items = json.loads(MERGED.read_text(encoding="utf-8"))
    n_doc_field = sum(
        1 for it in items for doc in (it.get("documents") or [])
        if "std_name" in doc)
    if not n_doc_field:
        print("경고: documents에 std_name이 없음 — standardize_docs.py를 먼저 실행하세요.")

    n = 0
    for it in items:
        if not it.get("servId"):
            continue
        upsert_eligibility(con, it)
        replace_documents(con, it)
        n += 1
    con.commit()

    elig = con.execute("SELECT COUNT(*) FROM eligibility").fetchone()[0]
    rdoc = con.execute("SELECT COUNT(*) FROM req_documents").fetchone()[0]
    matched = con.execute(
        "SELECT COUNT(*) FROM eligibility e "
        "WHERE EXISTS (SELECT 1 FROM services s WHERE s.serv_id = e.serv_id)"
    ).fetchone()[0]
    print(f"적재 항목: {n}건")
    print(f"  eligibility: {elig}건")
    print(f"  req_documents: {rdoc}건")
    print(f"  services 테이블과 servId 매칭: {matched}/{elig}건")
    con.close()


if __name__ == "__main__":
    main()
