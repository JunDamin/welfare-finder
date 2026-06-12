"""DB(정본) -> 사이트 서빙 JSON export. index.html은 COLLECTED_AT 상수만 갱신.

산출(파일명 현행 유지 — index.html 무수정 원칙):
  data/welfare_full.json     services 테이블 전체 (스키마·키 순서 v2와 동일)
  data/central_details.json  중앙+지자체 상세 병합 {servId: {...}} (키는 servId라 충돌 없음)
  index.html                 var COLLECTED_AT = "YYYY-MM-DD" 상수 교체

추가(자격/서류 — eligibility/req_documents 테이블에서 생성):
  data/eligibility.json      { servId: {income, age, categories, exclusions,
                               documents:[{std_name,kind,source}], doc_summary,
                               eligibility_summary, confidence, notes} }
  data/doc_index.json        { 표준서류명: {count, servIds:[상위200], kind} } 역색인

사용:
  python export_site.py          # 전체(welfare_full/central_details/index.html)
  python export_site.py --elig   # eligibility.json + doc_index.json 만 (정본 무수정)
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


def export_eligibility(con) -> None:
    """eligibility + req_documents -> data/eligibility.json, data/doc_index.json."""
    # 서류를 servId별로 모아둠 (eligibility.json·doc_index.json 양쪽에서 사용)
    docs_by_serv: dict[str, list] = {}
    doc_index: dict[str, dict] = {}
    for r in con.execute(
            "SELECT serv_id, std_name, raw_name, kind, source FROM req_documents "
            "ORDER BY rowid"):
        docs_by_serv.setdefault(r["serv_id"], []).append(
            {"std_name": r["std_name"], "kind": r["kind"], "source": r["source"]})
        std = r["std_name"]
        ent = doc_index.setdefault(std, {"count": 0, "servIds": [], "kind": r["kind"]})
        ent["count"] += 1
        if len(ent["servIds"]) < 200 and r["serv_id"] not in ent["servIds"]:
            ent["servIds"].append(r["serv_id"])

    elig: dict[str, dict] = {}
    for r in con.execute("SELECT * FROM eligibility ORDER BY serv_id"):
        sid = r["serv_id"]
        elig[sid] = {
            "income": {
                "type": r["income_type"], "median_pct": r["income_pct"],
                "bound": r["income_bound"], "raw": r["income_raw"],
                "confidence": r["income_conf"],
            },
            "age": {
                "min": r["age_min"], "max": r["age_max"], "unit": r["age_unit"],
                "raw": r["age_raw"], "confidence": r["age_conf"],
            },
            "categories": json.loads(r["req_categories"]),
            "exclusions": json.loads(r["exclusions"]),
            "documents": docs_by_serv.get(sid, []),
            "doc_summary": r["doc_summary"],
            "eligibility_summary": r["eligibility_summary"],
            "confidence": r["overall_conf"],
            "notes": r["notes"],
        }

    (DATA / "eligibility.json").write_text(
        json.dumps(elig, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"eligibility.json: {len(elig)}건")

    # doc_index: count 내림차순 정렬해 출력(가독·디버그용)
    doc_index_sorted = dict(
        sorted(doc_index.items(), key=lambda kv: (-kv[1]["count"], kv[0])))
    (DATA / "doc_index.json").write_text(
        json.dumps(doc_index_sorted, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"doc_index.json: {len(doc_index_sorted)}개 표준서류")


def main() -> None:
    con = db.connect()

    # --elig: 정본(welfare_full/index.html)은 건드리지 않고 자격/서류만 export
    if "--elig" in sys.argv:
        export_eligibility(con)
        con.close()
        return

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

    # 4) eligibility.json + doc_index.json
    export_eligibility(con)
    con.close()


if __name__ == "__main__":
    main()
