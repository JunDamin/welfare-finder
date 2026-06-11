"""DB(정본) -> 사이트 서빙 JSON export. index.html은 COLLECTED_AT 상수만 갱신.

산출(파일명 현행 유지 — index.html 무수정 원칙):
  data/welfare_full.json     services 테이블 전체 (스키마·키 순서 v2와 동일)
  data/central_details.json  중앙+지자체 상세 병합 {servId: {...}} (키는 servId라 충돌 없음)
  index.html                 var COLLECTED_AT = "YYYY-MM-DD" 상수 교체
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402

BASE = db.BASE
DATA = BASE / "data"

# v2 welfare_full.json의 실측 키 순서 (kind별로 다름 — export 시 그대로 재현)
CENTRAL_KEYS = ["id", "name", "tags", "themes", "benefit", "how_to_apply", "agency",
                "contact", "source_url", "confidence", "online", "cycle",
                "provision", "ministry"]
LOCAL_KEYS = ["id", "name", "tags", "themes", "benefit", "how_to_apply", "agency",
              "contact", "source_url", "confidence", "region", "cycle", "provision"]


def service_row_to_obj(row) -> dict:
    base = {
        "id": row["serv_id"], "name": row["name"],
        "tags": json.loads(row["tags"]), "themes": json.loads(row["themes"]),
        "benefit": row["benefit"], "how_to_apply": row["how_to_apply"],
        "agency": row["agency"], "contact": row["contact"],
        "source_url": row["source_url"], "confidence": row["confidence"],
        "cycle": row["cycle"], "provision": row["provision"],
    }
    if row["kind"] == "central":
        base["online"] = bool(row["online"])
        base["ministry"] = row["ministry"] if row["ministry"] is not None else ""
        keys = CENTRAL_KEYS
    else:
        base["region"] = row["region"] if row["region"] is not None else ""
        keys = LOCAL_KEYS
    return {k: base[k] for k in keys}


def main() -> None:
    con = db.connect()

    # 1) welfare_full.json — 시드 시점의 원본 순서 보존을 위해 rowid 순으로 출력
    rows = con.execute("SELECT * FROM services ORDER BY rowid").fetchall()
    full = [service_row_to_obj(r) for r in rows]
    (DATA / "welfare_full.json").write_text(
        json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"welfare_full.json: {len(full)}건")

    # 2) central_details.json — 중앙+지자체 상세 병합(servId 키, 충돌 없음)
    details: dict[str, dict] = {}
    for table in ("central_details", "local_details"):
        for r in con.execute(f"SELECT * FROM {table} ORDER BY serv_id"):
            details[r["serv_id"]] = db.detail_row_to_dict(r)
    (DATA / "central_details.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"central_details.json: {len(details)}건 (중앙+지자체 병합)")

    # 3) index.html의 COLLECTED_AT 상수 교체
    collected_at = db.get_meta(con, "collected_at")
    if collected_at:
        idx = BASE / "index.html"
        html = idx.read_text(encoding="utf-8")
        new_html, n = re.subn(r'(var COLLECTED_AT = ")[0-9-]+(")',
                              rf"\g<1>{collected_at}\g<2>", html)
        if n == 1 and new_html != html:
            idx.write_text(new_html, encoding="utf-8")
            print(f"index.html COLLECTED_AT -> {collected_at}")
        elif n != 1:
            print(f"경고: COLLECTED_AT 상수 매칭 {n}건 — index.html 미변경")
        else:
            print(f"index.html COLLECTED_AT 이미 {collected_at}")
    con.close()


if __name__ == "__main__":
    main()
