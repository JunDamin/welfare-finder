"""멱등 일일 상세 수집 — DB(data/welfare.db)에 없는 servId만 호출한다.

쿼터(희소자원): 중앙 상세 100/일, 지자체 상세 1,000/일.
안전선: 중앙 90건 / 지자체 950건까지만 호출. 이미 수집된 servId 재호출 0.

사용:
  python pipeline/collect_daily.py              # 운영 모드(중앙 90 + 지자체 950)
  python pipeline/collect_daily.py --limit 30   # 테스트 모드: 중앙 호출 0, 지자체 30건만

인증키: env DATA_GO_KR_KEY 우선, 없으면 ../playbook-dryrun-welfare-fasthtml/.apikey(로컬 전용).
보안: 키는 어떤 출력/로그/에러에도 노출하지 않는다(redact).
"""
import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from urllib.parse import quote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402

BASE = db.BASE

CENTRAL_DETAIL_URL = ("https://apis.data.go.kr/B554287/NationalWelfareInformationsV001/"
                      "NationalWelfaredetailedV001")
LOCAL_DETAIL_URL = ("https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/"
                    "LcgvWelfaredetailed")

CENTRAL_CAP = 90    # 일일 한도 100의 90%
LOCAL_CAP = 950     # 일일 한도 1,000의 95%
SLEEP = 0.15


def load_key() -> str:
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if key:
        return key
    fallback = BASE.parent / "playbook-dryrun-welfare-fasthtml" / ".apikey"
    if fallback.exists():
        return fallback.read_text(encoding="utf-8").strip()
    raise SystemExit("인증키 없음: env DATA_GO_KR_KEY 또는 드라이런 .apikey 필요")


API_KEY = load_key()


def redact(msg: object) -> str:
    out = str(msg).replace(API_KEY, "[KEY]")
    return out.replace(quote(API_KEY, safe=""), "[KEY]")


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()[:2000]


class QuotaExceeded(RuntimeError):
    """게이트웨이가 일일 트래픽 초과(코드 22)를 반환 — 해당 종류 수집 즉시 중단."""


def get_xml(client: httpx.Client, url: str, params: dict) -> ET.Element:
    """1회 재시도 + 게이트웨이 오류 판별. 키는 어디에도 출력하지 않는다."""
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            r = client.get(url, params={"serviceKey": API_KEY, **params}, timeout=30)
            r.raise_for_status()
            root = ET.fromstring(r.text)
            if root.tag == "OpenAPI_ServiceResponse":
                code = root.findtext(".//returnReasonCode") or "?"
                msg = root.findtext(".//returnAuthMsg") or ""
                if code.strip() == "22":
                    raise QuotaExceeded(f"일일 트래픽 초과 code={code}")
                raise RuntimeError(f"게이트웨이 오류 code={code} msg={msg}")
            return root
        except QuotaExceeded:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == 0:
                time.sleep(1.0)
    raise RuntimeError(redact(repr(last_err))[:300])


# ── 중앙 상세 파서 (드라이런 enrich_details.py에서 이전) ─────────────────
def _central_pairs(root: ET.Element, list_tag: str) -> list[tuple[str, str]]:
    out = []
    for el in root.iter(list_tag):
        name = clean(el.findtext("servSeDetailNm"))
        link = (el.findtext("servSeDetailLink") or "").strip()
        if name or link:
            out.append((name, link))
    return out


def parse_central(root: ET.Element, how_to_apply: str) -> dict:
    # 주의(함정): applmetList의 servSeDetailNm은 '신청기관연락처목록' 같은 카테고리
    # 라벨이라 신청방법으로 쓸 수 없음 — apply는 목록의 공식 how_to_apply에서 채운다.
    d = {
        "target": clean(root.findtext(".//tgtrDtlCn")),
        "criteria": clean(root.findtext(".//slctCritCn")),
        "content": clean(root.findtext(".//alwServCn")),
        "apply": apply_from_how(how_to_apply),
        "forms": [{"name": n, "link": l} for n, l in _central_pairs(root, "basfrmList")],
        "laws": [n for n, _ in _central_pairs(root, "baslawList") if n],
        "contacts": [f"{n} {l}".strip() for n, l in _central_pairs(root, "inqplCtadrList")],
        "homepages": [{"name": n, "link": l}
                      for n, l in _central_pairs(root, "inqplHmpgReldList")],
    }
    if not d["content"]:
        d["content"] = clean(root.findtext(".//wlfareInfoOutlCn"))
    return d


def apply_from_how(how_to_apply: str) -> list[str]:
    """'인터넷,방문 — 복지로 상세 참조' -> ['인터넷', '방문']."""
    head = (how_to_apply or "").split(" — ")[0].strip()
    if not head or "복지로 상세" in head:
        return []
    return [m.strip() for m in head.split(",") if m.strip()]


# ── 지자체 상세 파서 (탐침으로 확인한 응답 필드 기준) ────────────────────
# 응답 root=<wantedDtl>: sprtTrgtCn(대상), slctCritCn(기준), alwServCn(내용),
# aplyMtdNm(방법명), aplyMtdCn(신청 절차 설명),
# 목록류는 wlfareInfoReldNm(이름)/wlfareInfoReldCn(값·링크) 쌍:
#   inqplCtadrList(문의처), baslawList(근거법령), basfrmList(서식),
#   inqplHmpgReldList(홈페이지 — 있을 때만)
def _local_pairs(root: ET.Element, list_tag: str) -> list[tuple[str, str]]:
    out = []
    for el in root.iter(list_tag):
        name = clean(el.findtext("wlfareInfoReldNm"))
        val = (el.findtext("wlfareInfoReldCn") or "").strip()
        if name or val:
            out.append((name, val))
    return out


def parse_local(root: ET.Element) -> dict:
    code = (root.findtext("resultCode") or "").strip()
    if code not in ("", "0", "00"):
        raise RuntimeError(f"resultCode={code} msg={clean(root.findtext('resultMessage'))[:100]}")
    apply = [m.strip() for m in (root.findtext("aplyMtdNm") or "").split(",") if m.strip()]
    mtd_cn = clean(root.findtext("aplyMtdCn"))
    if mtd_cn:  # 신청 절차 설명도 같은 배열에 덧붙임(스키마 동일: 문자열 배열)
        apply.append(mtd_cn)
    d = {
        "target": clean(root.findtext("sprtTrgtCn")),
        "criteria": clean(root.findtext("slctCritCn")),
        "content": clean(root.findtext("alwServCn")),
        "apply": apply,
        "forms": [{"name": n, "link": v} for n, v in _local_pairs(root, "basfrmList")],
        "laws": [n for n, _ in _local_pairs(root, "baslawList") if n],
        "contacts": [f"{n} {v}".strip() for n, v in _local_pairs(root, "inqplCtadrList")],
        "homepages": [{"name": n, "link": v}
                      for n, v in _local_pairs(root, "inqplHmpgReldList")],
    }
    if not d["content"]:
        d["content"] = clean(root.findtext("servDgst"))
    return d


# ── 수집 루프 ──────────────────────────────────────────────────────────
def pending(con, kind: str, table: str, cap: int) -> list:
    order = ("ORDER BY s.priority IS NULL, s.priority, s.serv_id"
             if kind == "central" else "ORDER BY s.serv_id")
    return con.execute(
        f"SELECT s.serv_id, s.how_to_apply FROM services s "
        f"LEFT JOIN {table} d ON d.serv_id = s.serv_id "
        f"WHERE s.kind = ? AND d.serv_id IS NULL {order} LIMIT ?",
        (kind, cap)).fetchall()


def collect(con, client: httpx.Client, kind: str, cap: int) -> tuple[int, int]:
    """returns (호출 수, 수집 수)."""
    table = "central_details" if kind == "central" else "local_details"
    url = CENTRAL_DETAIL_URL if kind == "central" else LOCAL_DETAIL_URL
    todo = pending(con, kind, table, cap)
    label = "중앙" if kind == "central" else "지자체"
    print(f"[{label}] 미수집 대상 {len(todo)}건 (호출 상한 {cap})")
    calls = ok = 0
    today = date.today().isoformat()
    for row in todo:
        sid = row["serv_id"]
        calls += 1
        try:
            if kind == "central":
                root = get_xml(client, url, {"callTp": "D", "servId": sid})
                d = parse_central(root, row["how_to_apply"])
            else:
                root = get_xml(client, url, {"servId": sid})
                d = parse_local(root)
            db.insert_detail(con, table, sid, d, today)
            ok += 1
        except QuotaExceeded as e:
            print(f"  {label} 쿼터 도달 — 중단: {redact(e)}")
            break
        except Exception as e:  # noqa: BLE001
            print(f"  실패 {sid}: {redact(e)[:200]}")
        if ok and ok % 50 == 0:
            con.commit()
        if calls % 50 == 0:
            print(f"  진행 {calls}/{len(todo)} (수집 {ok})")
        time.sleep(SLEEP)
    con.commit()
    print(f"[{label}] 호출 {calls} / 수집 {ok}")
    return calls, ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None,
                    help="테스트 모드: 중앙 호출 0, 지자체 상세 호출을 N건으로 제한")
    ap.add_argument("--central-cap", type=int, default=CENTRAL_CAP)
    ap.add_argument("--local-cap", type=int, default=LOCAL_CAP)
    args = ap.parse_args()

    central_cap = 0 if args.limit is not None else min(args.central_cap, CENTRAL_CAP)
    local_cap = (min(args.limit, LOCAL_CAP) if args.limit is not None
                 else min(args.local_cap, LOCAL_CAP))

    con = db.connect()
    client = httpx.Client()
    total_ok = 0
    try:
        if central_cap > 0:
            _, n = collect(con, client, "central", central_cap)
            total_ok += n
        else:
            print("[중앙] 호출 생략(테스트 모드 또는 상한 0)")
        if local_cap > 0:
            _, n = collect(con, client, "local", local_cap)
            total_ok += n
    finally:
        client.close()

    if total_ok:
        db.set_meta(con, "collected_at", date.today().isoformat())
        con.commit()

    nc = con.execute("SELECT COUNT(*) AS n FROM central_details").fetchone()["n"]
    nl = con.execute("SELECT COUNT(*) AS n FROM local_details").fetchone()["n"]
    print(f"\n누적 상세: 중앙 {nc} / 지자체 {nl} / 합계 {nc + nl}")
    con.close()


if __name__ == "__main__":
    main()
