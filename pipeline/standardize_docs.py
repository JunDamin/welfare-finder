"""서류명 표준화 사전 구축·적용 (controlled vocabulary).

입력:  _ext/merged.json 의 documents[].name
산출:  data/doc_vocab.json  { "_map": {원표기: 표준명}, "_kind": {표준명: kind} }
       merged.json 각 항목 documents[]에 std_name 필드 추가(in-place 갱신)

표준화 원칙(보수적):
  1) 표기변이만 자동 통합 — 공백/중점(·・‧) 정규화로 같아지는 surface form 들은
     그 그룹에서 가장 빈도가 높은(동률이면 공백 포함된 가독형) 표기를 표준명으로.
     예) '통장사본'='통장 사본' -> '통장 사본'
  2) 명백한 동의어만 소수 큐레이션(SYNONYMS). 의미가 갈릴 여지가 있으면 분리 유지.
  3) 한정어(본인/유족/대리인/사본 등)가 붙은 변형은 의미가 다를 수 있으므로 통합하지 않음.
  4) 원표기(raw_name)는 항상 보존. std_name은 부가 필드.

표준명별 kind: 해당 표준명으로 묶인 원표기들의 최빈 kind.
"""
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
MERGED = BASE / "_ext" / "merged.json"
VOCAB = BASE / "data" / "doc_vocab.json"

# 공백/중점류 제거 후 비교용 정규화 키
_MIDDOT = "·・‧･"


def norm_key(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    for ch in _MIDDOT:
        s = s.replace(ch, "")
    s = re.sub(r"\s+", "", s)
    return s


# 명백한 동의어만 큐레이션 (좌 원표기 -> 우 표준명). 표준명은 가독형으로.
# 표기변이 자동통합 후에도 남는, 의미가 동일함이 분명한 쌍만.
SYNONYMS = {
    "주민등록표 등본": "주민등록등본",
    "주민등록 등본": "주민등록등본",
    "주민등록표등본": "주민등록등본",
    "주민등록표 초본": "주민등록초본",
    "주민등록 초본": "주민등록초본",
    "예금통장 사본": "통장 사본",
    "예금통장사본": "통장 사본",
    "통장": "통장 사본",
    "가족관계증명서(상세)": "가족관계증명서",
    "사회보장급여 신청(변경)서": "사회보장급여 신청(변경)서",
    "사회보장급여신청(변경)서": "사회보장급여 신청(변경)서",
}


def collect_names(items):
    freq = Counter()
    kinds = defaultdict(Counter)
    for it in items:
        for doc in it.get("documents") or []:
            n = (doc.get("name") or "").strip()
            if not n:
                continue
            freq[n] += 1
            kinds[n][doc.get("kind") or "기타"] += 1
    return freq, kinds


def build_vocab(items):
    freq, kinds = collect_names(items)

    # 1) 표기변이 그룹핑: norm_key 가 같은 surface form 끼리 묶고 대표 표기 선정
    groups = defaultdict(list)  # norm_key -> [(name, count)]
    for n, c in freq.items():
        groups[norm_key(n)].append((n, c))

    surface_to_std = {}  # 원표기 -> (표기변이 통합 후) 표준명
    for key, members in groups.items():
        # 대표 선정 = 가독형 우선. 공백/중점은 가독성 정보이므로 살린다.
        #   1) 중점(·)이 들어간 표기 우선(예: '소득·재산' > '소득재산')
        #   2) 공백이 더 많은 표기 우선(예: '통장 사본' > '통장사본')
        #   3) 그다음 빈도 desc, 길이 desc
        def midpoints(s):
            return sum(s.count(ch) for ch in _MIDDOT)
        rep = sorted(
            members,
            key=lambda nc: (-midpoints(nc[0]), -nc[0].count(" "), -nc[1], -len(nc[0])),
        )[0][0]
        for n, _ in members:
            surface_to_std[n] = rep

    # 2) 동의어 큐레이션 적용 (표기변이 통합 결과 위에 덮어씀)
    #    SYNONYMS 의 좌변/우변 모두 표기변이 정규화를 거쳐 매칭
    norm_syn = {norm_key(k): v for k, v in SYNONYMS.items()}
    final_map = {}
    for surface, std in surface_to_std.items():
        # std(또는 surface)가 동의어 사전에 걸리면 치환
        std_norm = norm_key(std)
        if std_norm in norm_syn:
            final_map[surface] = norm_syn[std_norm]
        elif norm_key(surface) in norm_syn:
            final_map[surface] = norm_syn[norm_key(surface)]
        else:
            final_map[surface] = std

    # 3) 표준명별 kind: 묶인 원표기들의 최빈 kind
    std_kind_counter = defaultdict(Counter)
    for surface, std in final_map.items():
        for k, c in kinds[surface].items():
            std_kind_counter[std][k] += c
    std_kind = {std: ctr.most_common(1)[0][0] for std, ctr in std_kind_counter.items()}

    return final_map, std_kind, freq


def apply_std(items, final_map):
    for it in items:
        for doc in it.get("documents") or []:
            n = (doc.get("name") or "").strip()
            doc["std_name"] = final_map.get(n, n)
    return items


def main():
    items = json.loads(MERGED.read_text(encoding="utf-8"))
    final_map, std_kind, freq = build_vocab(items)

    before = len(freq)
    after = len(set(final_map.values()))
    print(f"표준화 전 서류 종류수: {before}")
    print(f"표준화 후 서류 종류수: {after}  (통합 {before - after}건)")

    vocab = {"_map": final_map, "_kind": std_kind}
    VOCAB.write_text(json.dumps(vocab, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"사전 저장: {VOCAB.relative_to(BASE)}  ({VOCAB.stat().st_size:,} bytes)")

    apply_std(items, final_map)
    MERGED.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"std_name 부여 완료 -> {MERGED.relative_to(BASE)}")


if __name__ == "__main__":
    main()
