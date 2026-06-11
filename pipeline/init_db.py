"""기존 산출물을 SQLite 정본(data/welfare.db)으로 1회 적재(시드).

입력:
  data/welfare_full.json                 5,012건 목록 (v2 — 공식 API 병합본)
  data/central_details.json              중앙 상세 (드라이런에서 수집한 90건)
  <dryrun>/data/details_queue.json       중앙 상세 미수집 큐(우선순위 순) — 있으면
                                         services.priority로 보존, 없어도 동작

kind 판별: welfare_full.json 행에 'ministry'가 있으면 central, 'region'이 있으면 local
(v2 산출 규칙상 두 키는 상호배타적으로 존재).

재실행해도 안전(INSERT OR REPLACE 아님 — 이미 시드된 DB면 건너뜀).
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402

BASE = db.BASE
DATA = BASE / "data"
DRYRUN_DATA = BASE.parent / "playbook-dryrun-welfare-fasthtml" / "data"


def row_kind(r: dict) -> str:
    if "ministry" in r or "online" in r:
        return "central"
    if "region" in r:
        return "local"
    raise ValueError(f"kind 판별 불가: {r.get('id')}")


def main() -> None:
    con = db.connect()
    n_services = con.execute("SELECT COUNT(*) AS n FROM services").fetchone()["n"]
    if n_services:
        print(f"이미 시드됨(services {n_services}건) — 건너뜀. 재시드하려면 data/welfare.db 삭제.")
        con.close()
        return

    rows = json.loads((DATA / "welfare_full.json").read_text(encoding="utf-8"))

    # 중앙 상세 수집 우선순위: 드라이런의 잔여 큐 순서를 보존
    priority: dict[str, int] = {}
    queue_path = DRYRUN_DATA / "details_queue.json"
    if queue_path.exists():
        for i, sid in enumerate(json.loads(queue_path.read_text(encoding="utf-8"))):
            priority[sid] = i

    for r in rows:
        kind = row_kind(r)
        con.execute(
            "INSERT INTO services (serv_id, kind, name, tags, themes, benefit, "
            "how_to_apply, agency, contact, source_url, confidence, online, "
            "cycle, provision, ministry, region, priority) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (r["id"], kind, r["name"],
             json.dumps(r.get("tags", []), ensure_ascii=False),
             json.dumps(r.get("themes", []), ensure_ascii=False),
             r.get("benefit", ""), r.get("how_to_apply", ""),
             r.get("agency", ""), r.get("contact", ""),
             r.get("source_url", ""), r.get("confidence", ""),
             (1 if r["online"] else 0) if "online" in r else None,
             r.get("cycle", ""), r.get("provision", ""),
             r.get("ministry"), r.get("region"),
             priority.get(r["id"])))

    details = json.loads((DATA / "central_details.json").read_text(encoding="utf-8"))
    today = date.today().isoformat()
    seeded = 0
    central_ids = {row["serv_id"] for row in
                   con.execute("SELECT serv_id FROM services WHERE kind='central'")}
    for sid, d in details.items():
        table = "central_details" if sid in central_ids else "local_details"
        db.insert_detail(con, table, sid, d, today)
        seeded += 1

    db.set_meta(con, "seeded_at", today)
    db.set_meta(con, "collected_at", today)
    con.commit()

    for t in ("services", "central_details", "local_details", "meta"):
        n = con.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
        print(f"  {t}: {n}건")
    kinds = con.execute(
        "SELECT kind, COUNT(*) AS n FROM services GROUP BY kind").fetchall()
    print("  services 내역:", {row["kind"]: row["n"] for row in kinds})
    print(f"시드 완료 -> {db.DB_PATH.name} (상세 {seeded}건 포함)")
    con.close()


if __name__ == "__main__":
    main()
