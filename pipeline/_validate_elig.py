"""적재·표준화·export 결과 검증.

검사:
  - eligibility.json 건수(1,079 기대)
  - 서류 표준화 전/후 종류수 (merged.json raw name vs std_name)
  - 공통서류 TOP15 (표준화 후, std_name 기준 등장 항목수)
  - 동시수급 배제(exclusions) 보유 건수
  - 통장사본류가 하나로 합쳐졌는지 확인
"""
import json
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
MERGED = BASE / "_ext" / "merged.json"


def main():
    elig = json.loads((DATA / "eligibility.json").read_text(encoding="utf-8"))
    items = json.loads(MERGED.read_text(encoding="utf-8"))

    print(f"[1] eligibility.json 건수: {len(elig)}  (기대 1079) -> "
          f"{'OK' if len(elig) == 1079 else 'FAIL'}")

    raw_types, std_types = set(), set()
    for it in items:
        for d in it.get("documents") or []:
            if d.get("name"):
                raw_types.add(d["name"].strip())
            if d.get("std_name"):
                std_types.add(d["std_name"].strip())
    print(f"[2] 서류 종류수  표준화 전: {len(raw_types)}  ->  후: {len(std_types)}  "
          f"(통합 {len(raw_types) - len(std_types)}건)")

    # 공통서류 TOP15: std_name 별 '등장한 항목 수'(servId 기준 중복 제거)
    serv_per_doc = Counter()
    for sid, v in elig.items():
        seen = {d["std_name"] for d in v.get("documents") or []}
        for nm in seen:
            serv_per_doc[nm] += 1
    print("[3] 공통서류 TOP15 (표준화 후, 항목수 기준):")
    for nm, c in serv_per_doc.most_common(15):
        print(f"      {c:4d}  {nm}")

    excl_cnt = sum(1 for v in elig.values() if v.get("exclusions"))
    print(f"[4] 동시수급/배제(exclusions) 보유 항목: {excl_cnt}건")

    # 통장사본 통합 확인
    bank = sorted(n for n in std_types if "통장" in n)
    print("[5] '통장' 포함 표준명 목록:")
    for n in bank:
        print(f"      {n!r}  (항목수 {serv_per_doc.get(n, 0)})")
    merged_ok = "통장사본" not in std_types and "통장 사본" in std_types
    print(f"    통장사본->통장 사본 통합: {'OK' if merged_ok else '확인필요'}")


if __name__ == "__main__":
    main()
