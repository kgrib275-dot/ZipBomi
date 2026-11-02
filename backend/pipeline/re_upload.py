"""실거래가 파일 업로드 — 국토교통부 실거래가 공개시스템(rt.molit.go.kr → 조건별 자료제공)에서 내려받은 CSV·XLSX 를
API 로 받은 것과 똑같은 표(rtms_<데이터셋>)·열로 넣는다. API 활용신청이 안 되는 데이터셋을 파일로 채우기 위한 것.

- 파일: CSV(CP949·EUC-KR 또는 UTF-8/BOM — 앞 1MB 로 판정), XLSX(openpyxl 읽기 전용, 첫 시트부터 머리글이 있는 시트).
  .xls(옛 엑셀)는 받지 않는다 — 사이트에서 CSV 로 받으면 된다.
- 머리글 줄: 앞쪽 안내문(보통 15줄 남짓) 다음에 '시군구'와 '계약년월'이 함께 있는 첫 줄 (앞 80줄 안).
- 데이터셋: 머리글 모양으로 판정(지목 → 토지, 건축물주용도 → 상업업무용, 분/입구분 → 분양권, 연면적·계약면적 → 단독다가구,
  대지권면적·건물명 → 연립다세대, 단지명 + 동 → 아파트 …). 아파트/오피스텔 전월세처럼 머리글이 같으면 파일 이름·안내문의 낱말로 가린다.
  관리자가 데이터셋을 직접 고르면 그것을 쓰되, 매매/전월세가 머리글과 맞지 않으면 거절한다.
- 각 줄은 공공데이터포털 API 와 같은 항목 이름(aptNm·excluUseAr·dealAmount …)의 dict 로 바꿔 raw 에 넣고,
  공통 열은 re_store.rtms_row 로 만든다 — 그래서 /re/data·지도(region_price_summary)·요약이 API 자료와 똑같이 동작한다.
- 지역: '시군구' 글자 → 5자리 코드 (re_store.lawd_from_address, regions_kr 목록에 있는 곳만). 못 찾으면 넣지 않고 '지역 불일치'로 센다.
- 중복: 같은 시군구·달 안에서 (계약일, 면적, 층, 금액, 보증금, 월세, 건축년도)가 같은 행이 이미 있으면(API 로 받은 행 포함) 넣지 않는다.
  같은 파일 안에 똑같은 거래가 두 번 있으면 둘 다 넣는다(여러 건 거래) — 기존 개수만큼만 중복으로 센다. 다시 올려도 늘지 않는다.
  업로드 행의 uid 는 'u' + 해시 (API 행은 16진 해시라 'u' 로 시작하지 않는다).
- API 배치가 나중에 같은 칸(시군구·달)을 받으면 replace_partition 이 칸을 통째로 바꾼다 — 같은 원천이므로 겹치지 않는다.
  업로드한 칸은 re_fetch_log 에 calls=0 으로 남겨 관리 화면 행 수·적용 범위에 잡히게 한다(이미 API 로 받은 칸은 행 수만 고친다).
- 기록: re_upload_log (이 모듈이 만든다 — db.py 를 고치지 않는다).
"""
from __future__ import annotations

import codecs
import csv

# 일부 국토부 CSV(토지·상업용 등)에 아주 긴 칸이 있어 기본 상한(131072자)에 걸렸다 (2026-11-02) — 상한을 넉넉히 올린다
csv.field_size_limit(16 * 1024 * 1024)
import hashlib
import json
import logging
import re
import threading
from collections import Counter
from pathlib import Path

from pipeline import db, re_store

log = logging.getLogger("zipgenie.re_upload")

MAX_BYTES = 60 * 1024 * 1024
EXTS = (".csv", ".xlsx")
HEADER_SCAN = 80
_lock = threading.Lock()

_LOG_SQL = ("CREATE TABLE IF NOT EXISTS re_upload_log (id INTEGER PRIMARY KEY AUTOINCREMENT, dataset TEXT NOT NULL, "
            "filename TEXT, size INTEGER, encoding TEXT, detected TEXT, rows_total INTEGER NOT NULL DEFAULT 0, "
            "inserted INTEGER NOT NULL DEFAULT 0, duplicates INTEGER NOT NULL DEFAULT 0, unmatched INTEGER NOT NULL DEFAULT 0, "
            "invalid INTEGER NOT NULL DEFAULT 0, months TEXT, ymd_from TEXT, ymd_to TEXT, regions INTEGER, "
            "uploaded_at TEXT NOT NULL, note TEXT)")


class UploadError(Exception):
    """화면에 그대로 보여도 되는 한국어 문구."""


# ───────────────────────── 파일 읽기 ─────────────────────────

def detect_encoding(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(1 << 20)
    if head.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    dec = codecs.getincrementaldecoder("utf-8")()
    try:
        dec.decode(head, final=False)  # 끝에서 잘린 글자는 오류로 보지 않는다
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "cp949"


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v).strip()


def _csv_rows(path: Path, enc: str):
    with open(path, encoding=enc, errors="replace", newline="") as f:
        sample = f.read(65536)
        f.seek(0)
        lines = sample.splitlines()[:HEADER_SCAN]
        delim = "\t" if sum(x.count("\t") for x in lines) > sum(x.count(",") for x in lines) else ","
        # 깨진 파일의 0 바이트(NUL)는 걸러 낸다 — 남은 정상 행은 살리고, 끊긴 행은 칸 수가 안 맞아 건너뛰어진다
        for row in csv.reader((line.replace("\x00", "") for line in f), delimiter=delim):
            yield [c.strip() for c in row]


def _xlsx_rows(path: Path):
    try:
        from openpyxl import load_workbook
    except ImportError as e:  # pragma: no cover
        raise UploadError("서버에 openpyxl 이 없어 XLSX 를 읽지 못합니다. CSV 로 올려 주세요.") from e
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise UploadError("XLSX 파일을 열지 못했습니다 (손상됐거나 엑셀 형식이 아닙니다).") from e
    try:
        ws = wb.worksheets[0]  # 공개시스템 엑셀은 시트 하나
        for row in ws.iter_rows(values_only=True):
            yield [_cell(v) for v in row]
    finally:
        wb.close()


def _norm(h: str) -> str:
    return re.sub(r"\s+", "", h or "")


def _is_header(cells: list[str]) -> bool:
    n = [_norm(c) for c in cells]
    return "시군구" in n and any(x.startswith("계약년월") for x in n)


# ───────────────────────── 데이터셋 판정 ─────────────────────────

_HINT_WORDS = {
    "apt": ("아파트",), "offi": ("오피스텔",), "rh": ("연립", "다세대"), "sh": ("단독", "다가구"),
    "silv": ("분양권", "입주권"), "land": ("토지",), "nrg": ("상업", "업무용"), "indu": ("공장", "창고"),
}


def _hint(text: str) -> set[str]:
    return {k for k, words in _HINT_WORDS.items() if any(w in text for w in words)}


def _has(H: list[str], *prefixes: str) -> bool:
    return any(h.startswith(p) for h in H for p in prefixes)


def detect_dataset(header: list[str], filename: str = "", notice: str = "") -> tuple[str | None, str]:
    """(데이터셋 키 또는 None, 판정 근거)."""
    H = [_norm(h) for h in header]
    rent = "전월세구분" in H or _has(H, "보증금")
    deal = "rent" if rent else "trade"
    fh, nh = _hint(filename), _hint(notice)

    def pick(*cands: str) -> str | None:
        for src in (fh, nh):  # 파일 이름이 먼저, 그다음 안내문
            hit = [c for c in cands if c in src]
            if len(hit) == 1:
                return hit[0]
        return None

    if "지목" in H:
        return "land_trade", "머리글 '지목'"
    if _has(H, "건축물주용도", "건축물용도"):
        return (pick("nrg", "indu") or "nrg") + "_trade", "머리글 '건축물주용도'"
    if any("분/입" in h or "분양/입주" in h for h in H):
        return "silv_trade", "머리글 '분/입구분'"
    if _has(H, "연면적", "계약면적") or ("주택유형" in H and not _has(H, "전용면적") and "단지명" not in H):
        return f"sh_{deal}", "머리글 '연면적·계약면적'"
    if _has(H, "대지권면적") or "건물명" in H:
        return f"rh_{deal}", "머리글 '대지권면적·건물명'"
    if "단지명" in H:
        p = pick("apt", "offi")
        if p:
            return f"{p}_{deal}", "파일 이름·안내문"
        if not rent:
            return ("apt_trade", "머리글 '동'") if "동" in H else ("offi_trade", "머리글에 '동' 없음")
        return None, "아파트/오피스텔 전월세는 머리글이 같아 자동으로 가리지 못했습니다"
    return None, "알 수 없는 머리글"


# ───────────────────────── 줄 → API 항목 ─────────────────────────

def _blank(v: str) -> str:
    v = (v or "").strip()
    return "" if v in ("-", "--", "N/A") else v


def _yymmdd(v: str) -> str:
    """'20250312' → '25.03.12' (API 표기). 이미 '25.03.12' 면 그대로."""
    d = re.sub(r"\D", "", v)
    if len(d) == 8:
        return f"{d[2:4]}.{d[4:6]}.{d[6:8]}"
    if len(d) == 6 and "." not in v:
        return f"{d[0:2]}.{d[2:4]}.{d[4:6]}"
    return v


def _term(v: str) -> str:
    """'202503~202703' → '25.03~27.03'."""
    parts = [re.sub(r"\D", "", p) for p in v.split("~")]
    if len(parts) == 2 and all(len(p) == 6 for p in parts):
        return "~".join(f"{p[2:4]}.{p[4:6]}" for p in parts)
    return v


# (머리글 시작 글자, API 항목) — 모든 데이터셋 공통. 앞에서부터 먼저 맞는 것.
_COMMON = [
    ("번지", "jibun"), ("본번", "bonbun"), ("부번", "bubun"), ("도로명", "roadNm"), ("계약일", "dealDay"),
    ("층", "floor"), ("건축년도", "buildYear"), ("거래유형", "dealingGbn"), ("중개사소재지", "estateAgentSggNm"),
    ("등기일자", "rgstDate"), ("매수자", "buyerGbn"), ("매도자", "slerGbn"), ("거래금액", "dealAmount"),
    ("보증금", "deposit"), ("월세", "monthlyRent"), ("계약기간", "contractTerm"), ("계약구분", "contractType"),
    ("갱신요구권", "useRRRight"), ("종전계약보증금", "preDeposit"), ("종전계약월세", "preMonthlyRent"),
    ("지분구분", "shareDealingType"), ("용도지역", "landUse"), ("도로조건", "roadCondition"), ("해제사유발생일", "cdealDay"),
    ("전월세구분", "rentGbn"),
]
_BY_PROP = {
    "apt": [("단지명", "aptNm"), ("동", "aptDong"), ("전용면적", "excluUseAr"), ("주택유형", "houseType")],
    "silv": [("단지명", "aptNm"), ("동", "aptDong"), ("전용면적", "excluUseAr"), ("분/입", "ownershipGbn"),
             ("분양/입주", "ownershipGbn")],
    "offi": [("단지명", "offiNm"), ("전용면적", "excluUseAr")],
    "rh": [("건물명", "mhouseNm"), ("단지명", "mhouseNm"), ("전용면적", "excluUseAr"), ("대지권면적", "landAr"),
           ("주택유형", "houseType")],
    "sh": [("주택유형", "houseType"), ("연면적", "totalFloorAr"), ("계약면적", "totalFloorAr"), ("대지면적", "plottageAr")],
    "land": [("지목", "jimok"), ("거래면적", "dealArea"), ("계약면적", "dealArea")],
    "nrg": [("유형", "buildingType"), ("건축물주용도", "buildingUse"), ("건축물용도", "buildingUse"),
            ("건물면적", "buildingAr"), ("전용면적", "buildingAr"), ("연면적", "buildingAr"), ("대지면적", "plottageAr")],
}
_EXACT = {"동", "층", "유형", "번지", "본번", "부번", "도로명", "계약일"}  # 다른 이름의 앞부분과 겹치는 짧은 이름은 정확히 같을 때만


def _colmap(header: list[str], key: str) -> dict[int, str]:
    prop = key.split("_")[0]
    rules = _BY_PROP.get("nrg" if prop == "indu" else prop, []) + _COMMON
    out: dict[int, str] = {}
    for i, h in enumerate(_norm(x) for x in header):
        for pre, tag in rules:
            if (h == pre) if pre in _EXACT else h.startswith(pre):
                if tag not in out.values():
                    out[i] = tag
                break
    return out


_CITY_TOK = re.compile(r".+(시|군|구)$")


def _umd(sgg_text: str) -> str:
    """'서울특별시 강남구 역삼동' → '역삼동', '경기도 성남시 분당구 정자동' → '정자동', '부산광역시 기장군 기장읍 청강리' → '기장읍 청강리'."""
    toks = sgg_text.split()[1:]
    while toks and _CITY_TOK.match(toks[0]) and len(toks) > 1:
        toks = toks[1:]
    return " ".join(toks)


def to_item(cells: list[str], cmap: dict[int, str], sgg_idx: int, ymd_idx: int) -> dict | None:
    """한 줄 → API 항목 dict. 계약년월이 없으면 None (끝의 합계·빈 줄)."""
    ymd = re.sub(r"\D", "", cells[ymd_idx] if ymd_idx < len(cells) else "")
    if len(ymd) != 6:
        return None
    it: dict[str, str] = {}
    for i, tag in cmap.items():
        if i < len(cells):
            it[tag] = _blank(cells[i])
    it["dealYear"], it["dealMonth"] = ymd[:4], str(int(ymd[4:]))
    if it.get("dealDay"):
        it["dealDay"] = str(re.sub(r"\D", "", it["dealDay"]) or "").lstrip("0") or ""
    sgg = cells[sgg_idx].strip() if sgg_idx < len(cells) else ""
    it["umdNm"] = _umd(sgg)
    it["sggNm"] = sgg
    if it.get("cdealDay"):
        it["cdealType"], it["cdealDay"] = "O", _yymmdd(it["cdealDay"])
    for k in ("rgstDate",):
        if it.get(k):
            it[k] = _yymmdd(it[k])
    if it.get("contractTerm"):
        it["contractTerm"] = _term(it["contractTerm"])
    it.pop("rentGbn", None)  # 전세/월세는 월세 금액으로 가린다 (API 에도 없는 항목)
    it["_src"] = "upload"
    return it


def _sig(r: dict) -> tuple:
    a = r.get("area")
    return (r.get("deal_date"), round(a, 2) if a else None, r.get("floor"), r.get("amount"), r.get("deposit"),
            r.get("monthly_rent"), r.get("build_year"))


# ───────────────────────── 넣기 ─────────────────────────

def _ensure_log(conn) -> None:
    conn.execute(_LOG_SQL)


def ingest(path: Path, filename: str, dataset: str | None = None, size: int = 0, note: str = "") -> dict:
    """파일 하나를 읽어 넣고 요약을 돌려준다. 잘못된 파일이면 UploadError. note 는 기록 메모 앞에 붙는다 (예: '자동 다운로드')."""
    ext = Path(filename).suffix.lower()
    if ext not in EXTS:
        raise UploadError("CSV 또는 XLSX 파일만 올릴 수 있습니다.")
    re_store.ensure_schema()
    keys = re_store.rtms_keys()
    if dataset and dataset not in keys:
        raise UploadError("없는 데이터셋입니다.")
    with _lock:  # 업로드는 한 번에 하나씩 (같은 칸에 동시에 넣어 중복 판정이 어긋나지 않게)
        return _ingest(path, filename, dataset, size, ext, keys, note)


def _ingest(path: Path, filename: str, dataset: str | None, size: int, ext: str, keys: list[str], tag: str = "") -> dict:
    enc = "xlsx" if ext == ".xlsx" else detect_encoding(path)
    rows_iter = _xlsx_rows(path) if ext == ".xlsx" else _csv_rows(path, enc)
    notice: list[str] = []
    header: list[str] | None = None
    for i, cells in enumerate(rows_iter):
        if _is_header(cells):
            header = cells
            break
        if i < HEADER_SCAN:
            notice.append(" ".join(c for c in cells if c))
        elif ext == ".csv":
            break
    if not header:
        raise UploadError("머리글 줄(시군구·계약년월)을 찾지 못했습니다. rt.molit.go.kr 에서 받은 원본 파일인지 확인해 주세요.")
    detected, why = detect_dataset(header, filename, "\n".join(notice))
    if dataset:
        if detected and detected.endswith("_rent") != dataset.endswith("_rent"):
            raise UploadError(f"고른 데이터셋과 파일이 맞지 않습니다 (파일은 {'전월세' if detected.endswith('_rent') else '매매'} 자료).")
        key = dataset
    elif detected and detected in keys:
        key = detected
    else:
        raise UploadError(f"자료 종류를 알아내지 못했습니다 — {why}. 데이터셋을 직접 골라 다시 올려 주세요.")
    H = [_norm(h) for h in header]
    sgg_idx = H.index("시군구")
    ymd_idx = next(i for i, h in enumerate(H) if h.startswith("계약년월"))
    cmap = _colmap(header, key)
    for need in (("dealAmount",) if not key.endswith("_rent") else ("deposit",)):
        if need not in cmap.values():
            raise UploadError("금액 열(거래금액 또는 보증금)이 없습니다. 파일을 확인해 주세요.")

    t = re_store.table(key)
    at = re_store._now()
    lawd_cache: dict[str, str | None] = {}
    existing: dict[tuple[str, str], Counter] = {}  # 칸별 기존 서명 → 아직 짝을 못 찾은 개수 (중복 판정용으로 줄어든다)
    orig: dict[tuple[str, str], Counter] = {}      # 칸별 기존 서명 → 처음 개수
    seq: dict[tuple, int] = {}                     # (칸, 서명) → 이번에 마지막으로 쓴 순번
    unmatched_names: Counter = Counter()
    total = inserted = dup = unmatched = invalid = 0
    months: set[str] = set()
    touched: set[tuple[str, str]] = set()
    regions: set[str] = set()
    batch: list[tuple] = []
    conn = db.connect()
    try:
        _ensure_log(conn)

        def flush():
            if batch:
                conn.executemany(
                    f"INSERT OR IGNORE INTO {t} (lawd_cd, deal_ymd, uid, deal_date, umd, jibun, name, kind, area, land_area, "
                    "floor, build_year, amount, deposit, monthly_rent, deal_type, cancelled, contract_type, contract_term, "
                    "raw, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                conn.commit()
                batch.clear()

        for cells in rows_iter:
            if not any(cells):
                continue
            it = to_item(cells, cmap, sgg_idx, ymd_idx)
            if it is None:
                if any(c for c in cells):
                    invalid += 1
                continue
            total += 1
            sgg = it["sggNm"]
            if sgg not in lawd_cache:
                lawd_cache[sgg] = re_store.lawd_from_address(sgg)[0]
            lawd = lawd_cache[sgg]
            if not lawd:
                unmatched += 1
                unmatched_names[" ".join(sgg.split()[:3])] += 1
                continue
            r = re_store.rtms_row(it)
            if r["amount"] is None and r["deposit"] is None:
                invalid += 1
                total -= 1
                continue
            ymd = f"{int(it['dealYear']):04d}{int(it['dealMonth']):02d}"
            part = (lawd, ymd)
            if part not in existing:
                c = Counter()
                for e in conn.execute(f"SELECT deal_date, area, floor, amount, deposit, monthly_rent, build_year FROM {t} "
                                      "WHERE lawd_cd=? AND deal_ymd=?", part):
                    c[_sig(dict(e))] += 1
                existing[part] = c
                orig[part] = Counter(c)
            s = _sig(r)
            months.add(ymd)
            if existing[part][s] > 0:
                existing[part][s] -= 1
                dup += 1
                continue
            raw = json.dumps(it, ensure_ascii=False, sort_keys=True)
            h = hashlib.sha1(repr((part, s)).encode()).hexdigest()[:20]
            # 같은 서명의 몇 번째 행인지 — 이미 있던 같은 서명 행 수부터 순번을 매겨 예전 업로드 행의 uid 와 겹치지 않게
            ps = (part, s)
            seq[ps] = seq[ps] + 1 if ps in seq else orig[part][s]
            uid = f"u{h}-{seq[ps]}"
            batch.append((lawd, ymd, uid, r["deal_date"], r["umd"], r["jibun"], r["name"], r["kind"], r["area"],
                          r["land_area"], r["floor"], r["build_year"], r["amount"], r["deposit"], r["monthly_rent"],
                          r["deal_type"], r["cancelled"], r["contract_type"], r["contract_term"], raw, at))
            inserted += 1
            touched.add(part)
            regions.add(lawd)
            if len(batch) >= 5000:
                flush()
        flush()
        # 관리 화면 행 수·적용 범위 (re_fetch_log) — 업로드만 있는 칸은 calls=0, API 로 받은 칸은 행 수만 고친다
        for lawd, ymd in touched:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE lawd_cd=? AND deal_ymd=?", (lawd, ymd)).fetchone()[0]
            conn.execute("INSERT INTO re_fetch_log (dataset, lawd_cd, deal_ymd, rows, calls, fetched_at) VALUES (?,?,?,?,0,?) "
                         "ON CONFLICT(dataset, lawd_cd, deal_ymd) DO UPDATE SET rows=excluded.rows", (key, lawd, ymd, cnt, at))
        conn.commit()
    finally:
        conn.close()
    if key == "apt_trade" and touched:
        _refresh_deals_cache(touched)

    ms = sorted(months)
    note = ""
    if unmatched:
        top = ", ".join(f"{k} {v:,}건" for k, v in unmatched_names.most_common(5))
        note = f"지원 지역 밖이라 넣지 않음: {top}"
    if tag:
        note = f"{tag} · {note}" if note else tag
    summary = {
        "dataset": key, "dataset_name": (re_store.dataset(key) or {}).get("name", key), "detected": detected,
        "detected_by": why, "filename": filename, "size": size, "encoding": enc, "rows_total": total, "inserted": inserted,
        "duplicates": dup, "unmatched": unmatched, "invalid": invalid, "regions": len(regions),
        "ymd_from": ms[0] if ms else None, "ymd_to": ms[-1] if ms else None, "months": len(ms), "note": note,
        "uploaded_at": at,
    }
    conn = db.connect()
    try:
        _ensure_log(conn)
        cur = conn.execute(
            "INSERT INTO re_upload_log (dataset, filename, size, encoding, detected, rows_total, inserted, duplicates, unmatched, "
            "invalid, months, ymd_from, ymd_to, regions, uploaded_at, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, filename, size, enc, detected, total, inserted, dup, unmatched, invalid, json.dumps(ms), summary["ymd_from"],
             summary["ymd_to"], len(regions), at, note))
        conn.commit()
        summary["id"] = cur.lastrowid
    finally:
        conn.close()
    log.info("실거래가 파일 업로드 %s %s: %d줄 → 새로 %d · 중복 %d · 지역 불일치 %d · 잘못된 줄 %d",
             key, filename, total, inserted, dup, unmatched, invalid)
    return summary


def _refresh_deals_cache(parts: set[tuple[str, str]]) -> None:
    """/re/deals 화면 캐시(re_apt_trade)에 업로드 행을 더한다 — 캐시에 이미 있는 거래(같은 날짜·면적·층·금액)는 빼고."""
    from pipeline import molit
    for lawd, ymd in parts:
        try:
            with re_store._conn() as c:
                raws = [r["raw"] for r in c.execute("SELECT raw FROM rtms_apt_trade WHERE lawd_cd=? AND deal_ymd=?",
                                                    (lawd, ymd))]
            rows = [x for x in (molit.parse_item(json.loads(r)) for r in raws) if x]
            conn = molit._conn()
            try:
                hit = conn.execute("SELECT rows FROM re_apt_trade WHERE lawd_cd=? AND deal_ymd=?", (lawd, ymd)).fetchone()
            finally:
                conn.close()
            if hit:
                old = json.loads(hit["rows"])
                have = Counter((x.get("date"), x.get("area"), x.get("floor"), x.get("amount")) for x in old)
                for x in rows:
                    k = (x["date"], x["area"], x["floor"], x["amount"])
                    if have[k] > 0:
                        have[k] -= 1
                    else:
                        old.append(x)
                rows = old
            molit._store(lawd, ymd, rows)
        except Exception:  # noqa: BLE001 - 화면 캐시 실패는 업로드를 막지 않는다
            log.debug("화면 캐시 갱신 실패 %s %s", lawd, ymd, exc_info=True)


def history(limit: int = 500) -> list[dict]:
    conn = db.connect()
    try:
        _ensure_log(conn)
        rows = [dict(r) for r in conn.execute("SELECT * FROM re_upload_log ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        conn.close()
    names = {d["key"]: d["name"] for d in re_store.datasets()}
    for r in rows:
        r["dataset_name"] = names.get(r["dataset"], r["dataset"])
        try:
            r["months"] = json.loads(r["months"] or "[]")
        except ValueError:
            r["months"] = []
    return rows


def uploaded_totals() -> dict[str, int]:
    """데이터셋별 업로드로 새로 넣은 행 누적 (관리 화면 표시용)."""
    conn = db.connect()
    try:
        _ensure_log(conn)
        return {r["dataset"]: int(r["n"] or 0) for r in
                conn.execute("SELECT dataset, SUM(inserted) AS n FROM re_upload_log GROUP BY dataset")}
    finally:
        conn.close()


def save_stream(src, dst: Path, limit: int = MAX_BYTES) -> int:
    """업로드 본문을 조금씩 임시 파일로 — limit 을 넘으면 UploadError."""
    n = 0
    with open(dst, "wb") as out:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            n += len(chunk)
            if n > limit:
                raise UploadError(f"파일이 너무 큽니다 (최대 {limit // (1024 * 1024)}MB). 기간·지역을 나눠 받아 주세요.")
            out.write(chunk)
    if n == 0:
        raise UploadError("빈 파일입니다.")
    return n


__all__ = ["ingest", "history", "uploaded_totals", "save_stream", "UploadError", "MAX_BYTES", "EXTS", "detect_dataset"]
