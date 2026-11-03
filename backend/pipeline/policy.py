"""현행 수치 (/now) — 대출 규제·세율·청약·금리처럼 자주 바뀌는 숫자를 한곳에서 관리한다 (Phase 3, 2026-11-02).

- policy_params: 항목 하나 = 숫자 하나. 값·단위·적용 범위·기준일·근거(이름·링크)·상태(draft/published)를 함께 둔다.
  공개 화면(/now·노트·계산기)에는 published 만 나간다. 값이 바뀌면 직전 값(prev_*)과 바뀐 날(changed_on)을 남겨 '변경됨' 배지를 단다.
- policy_param_history: 값이 바뀔 때마다 한 줄 (관리 화면 이력·감사용).
- 자동 항목(source_kind='auto'): 기준금리(re_base_rate)·주담대 신규 금리(re_econ_series)는 수집된 표에서 읽어 채운다 — 사람이 고치지 않는다.
- 법령 수치 중 확인이 덜 된 값(LTV·스트레스 DSR·중과세율 등)은 draft 로 넣어 두고 관리자가 근거를 확인한 뒤 게시한다.
- notes.policy_params: 노트가 다루는 항목 키 JSON 배열. 비어 있으면(NULL) 제목·태그·본문 키워드로 채운다 (LLM 없음).
LLM·외부 호출 없음.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timedelta

from pipeline import db

GROUPS = ["대출 규제", "금리", "시장 심리·대출", "세금", "청약"]
CHANGED_DAYS = 30  # 바뀐 지 이 날수 안이면 '변경됨' 배지

LAW_TAX = "https://www.law.go.kr/%EB%B2%95%EB%A0%B9/%EC%A7%80%EB%B0%A9%EC%84%B8%EB%B2%95"  # 지방세법
LAW_SUPPLY = "https://www.law.go.kr/%EB%B2%95%EB%A0%B9/%EC%A3%BC%ED%83%9D%EA%B3%B5%EA%B8%89%EC%97%90%EA%B4%80%ED%95%9C%EA%B7%9C%EC%B9%99"  # 주택공급에 관한 규칙
FSC = "https://www.fsc.go.kr/no010101"  # 금융위원회 보도자료
BOK_RATE = "https://www.bok.or.kr/portal/singl/baseRate/list.do?dataSeCd=01&menuNo=200643"
ECOS = "https://ecos.bok.or.kr/"

# 처음 넣는 값. status 가 draft 인 항목은 근거를 관리자가 확인한 뒤에만 공개된다 (값을 지어내 공개하지 않으려는 장치).
SEED: list[dict] = [
    # 대출 규제 — 정책으로 자주 바뀐다: 전부 draft 로 시작
    {"key": "dsr_bank", "grp": "대출 규제", "label": "DSR 한도 (은행권)", "value": 40, "unit": "%",
     "scope": "총대출 1억원 초과 차주", "effective_on": "2022-07-01", "source_name": "금융위원회 가계부채 관리방안",
     "source_url": FSC, "status": "draft", "calc": "dsr", "sort": 10,
     "note": "연소득 대비 모든 대출의 연 원리금 비율 상한"},
    {"key": "dsr_nonbank", "grp": "대출 규제", "label": "DSR 한도 (2금융권)", "value": 50, "unit": "%",
     "scope": "총대출 1억원 초과 차주", "effective_on": "2022-07-01", "source_name": "금융위원회 가계부채 관리방안",
     "source_url": FSC, "status": "draft", "sort": 11},
    {"key": "stress_dsr", "grp": "대출 규제", "label": "스트레스 DSR 가산 금리 (수도권 주담대)", "value": 1.5, "unit": "%p",
     "scope": "수도권 주택담보대출 · 3단계", "effective_on": "2025-07-01", "source_name": "금융위원회 스트레스 DSR 3단계",
     "source_url": FSC, "status": "draft", "sort": 12, "note": "DSR 계산 때만 금리에 더하는 값 (실제 이자에는 붙지 않음)"},
    {"key": "ltv_regulated", "grp": "대출 규제", "label": "LTV (규제지역 · 무주택)", "value": 40, "unit": "%",
     "scope": "투기과열지구·조정대상지역", "effective_on": "", "source_name": "금융위원회 주택담보대출 규제",
     "source_url": FSC, "status": "draft", "calc": "ltv", "sort": 20},
    {"key": "ltv_nonregulated", "grp": "대출 규제", "label": "LTV (비규제지역)", "value": 70, "unit": "%",
     "scope": "규제지역 밖", "effective_on": "", "source_name": "금융위원회 주택담보대출 규제",
     "source_url": FSC, "status": "draft", "calc": "ltv", "sort": 21},
    {"key": "ltv_first_home", "grp": "대출 규제", "label": "LTV (생애최초 · 수도권·규제지역)", "value": 70, "unit": "%",
     "scope": "생애최초 주택 구입", "effective_on": "", "source_name": "금융위원회 가계부채 관리 강화 방안",
     "source_url": FSC, "status": "draft", "calc": "ltv", "sort": 22},
    {"key": "mortgage_cap_capital", "grp": "대출 규제", "label": "주담대 최대 금액 (수도권·규제지역)", "value": 60000, "unit": "만원",
     "scope": "구입 목적 주택담보대출", "effective_on": "", "source_name": "금융위원회 가계부채 관리 강화 방안",
     "source_url": FSC, "status": "draft", "sort": 23},
    # 금리 — 자동 (수집 표에서 읽음)
    {"key": "base_rate", "grp": "금리", "label": "한국은행 기준금리", "unit": "%", "scope": "전국",
     "source_name": "한국은행 기준금리 변경 추이", "source_url": BOK_RATE, "source_kind": "auto", "status": "published", "sort": 30},
    {"key": "mortgage_rate", "grp": "금리", "label": "주택담보대출 평균 금리 (신규취급액)", "unit": "%", "scope": "예금은행 · 월평균",
     "source_name": "한국은행 경제통계시스템(ECOS)", "source_url": ECOS, "source_kind": "auto", "status": "published",
     "calc": "rate", "sort": 31},
    # 시장 심리·대출 — 자동 (한국은행 ECOS, 2026-11-02 추가)
    {"key": "house_outlook_csi", "grp": "시장 심리·대출", "label": "주택가격전망지수 (소비자동향조사)", "unit": "", "scope": "전국 · 월",
     "source_name": "한국은행 소비자동향조사", "source_url": ECOS, "source_kind": "auto", "status": "published", "sort": 35,
     "note": "100보다 크면 1년 뒤 집값이 오를 것으로 보는 사람이 더 많다는 뜻"},
    {"key": "housing_loan_balance", "grp": "시장 심리·대출", "label": "주택관련 가계대출 잔액", "unit": "조원", "scope": "예금취급기관 · 월말",
     "source_name": "한국은행 경제통계시스템(ECOS)", "source_url": ECOS, "source_kind": "auto", "status": "published", "sort": 36},
    # 세금 — 지방세법 조문 그대로인 표준세율은 공개, 중과세율은 개정 논의가 잦아 확인 뒤 공개
    {"key": "acq_std_low", "grp": "세금", "label": "주택 취득세 표준세율 (6억원 이하)", "value": 1, "unit": "%",
     "scope": "유상취득 · 1주택 등 중과 아님", "effective_on": "2020-01-01", "source_name": "지방세법 제11조 제1항 제8호",
     "source_url": LAW_TAX, "status": "published", "sort": 40},
    {"key": "acq_std_mid", "grp": "세금", "label": "주택 취득세 표준세율 (6억 초과 9억원 이하)", "value_text": "(취득가액[억원] × 2/3 − 3)%",
     "unit": "", "scope": "유상취득 · 1~3%를 0.01%p 단위로", "effective_on": "2020-01-01",
     "source_name": "지방세법 제11조 제1항 제8호", "source_url": LAW_TAX, "status": "published", "sort": 41},
    {"key": "acq_std_high", "grp": "세금", "label": "주택 취득세 표준세율 (9억원 초과)", "value": 3, "unit": "%",
     "scope": "유상취득 · 중과 아님", "effective_on": "2020-01-01", "source_name": "지방세법 제11조 제1항 제8호",
     "source_url": LAW_TAX, "status": "published", "sort": 42},
    {"key": "acq_heavy2", "grp": "세금", "label": "취득세 중과 (조정 2주택·비조정 3주택)", "value": 8, "unit": "%",
     "scope": "일시적 2주택 제외", "effective_on": "2020-08-12", "source_name": "지방세법 제13조의2",
     "source_url": LAW_TAX, "status": "draft", "calc": "heavy2", "sort": 43},
    {"key": "acq_heavy3", "grp": "세금", "label": "취득세 중과 (조정 3주택·4주택 이상)", "value": 12, "unit": "%",
     "scope": "법인 취득 포함", "effective_on": "2020-08-12", "source_name": "지방세법 제13조의2",
     "source_url": LAW_TAX, "status": "draft", "calc": "heavy3", "sort": 44},
    # 청약
    {"key": "sub_score_max", "grp": "청약", "label": "청약 가점 만점", "value": 84, "unit": "점",
     "scope": "무주택 기간 32 · 부양가족 35 · 통장 가입 17", "effective_on": "", "source_name": "주택공급에 관한 규칙 별표 1",
     "source_url": LAW_SUPPLY, "status": "published", "sort": 50},
]

# 노트 → 항목 키 (제목·태그·요약·본문 키워드). 앞에서부터 맞는 규칙을 모두 더한다.
NOTE_RULES: list[tuple[str, list[str]]] = [
    (r"LTV|담보인정비율", ["ltv_regulated", "ltv_nonregulated", "ltv_first_home"]),
    (r"주담대\s*(한도|상한)|대출\s*한도|6억\s*(원)?\s*(한도|상한)", ["mortgage_cap_capital"]),
    (r"스트레스\s*DSR", ["stress_dsr"]),
    (r"DSR|총부채원리금", ["dsr_bank", "dsr_nonbank"]),
    (r"기준금리", ["base_rate"]),
    (r"(주담대|주택담보대출|대출)\s*금리", ["mortgage_rate"]),
    (r"취득세", ["acq_std_low", "acq_std_mid", "acq_std_high"]),
    (r"취득세[^.\n]{0,30}중과|중과[^.\n]{0,10}취득세", ["acq_heavy2", "acq_heavy3"]),  # '종부세 중과'는 아님
    (r"가점|청약\s*점수", ["sub_score_max"]),
]

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS policy_params (key TEXT PRIMARY KEY, grp TEXT NOT NULL, label TEXT NOT NULL, "
    "value REAL, value_text TEXT NOT NULL DEFAULT '', unit TEXT NOT NULL DEFAULT '', scope TEXT NOT NULL DEFAULT '', "
    "effective_on TEXT NOT NULL DEFAULT '', source_name TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '', "
    "source_kind TEXT NOT NULL DEFAULT 'manual', status TEXT NOT NULL DEFAULT 'draft', note TEXT NOT NULL DEFAULT '', "
    "calc TEXT NOT NULL DEFAULT '', sort INTEGER NOT NULL DEFAULT 0, prev_value REAL, prev_text TEXT, changed_on TEXT, "
    "checked_on TEXT, updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS policy_param_history (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, "
    "value REAL, value_text TEXT, effective_on TEXT, source_url TEXT, by TEXT, at TEXT NOT NULL)",
]
_FIELDS = ("grp", "label", "value", "value_text", "unit", "scope", "effective_on", "source_name", "source_url",
           "source_kind", "status", "note", "calc", "sort")
EDITABLE = ("label", "value", "value_text", "unit", "scope", "effective_on", "source_name", "source_url", "status",
            "note", "checked_on")
_ready: set[str] = set()
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(db.KST).isoformat(timespec="seconds")


def ensure() -> None:
    """표·노트 열을 만들고 처음 값(SEED)을 넣는다 — 이미 있는 항목은 건드리지 않는다 (관리자가 고친 값 보존)."""
    path = str(db.DB_PATH)
    if path in _ready:
        return
    with _lock:
        if path in _ready:
            return
        conn = db.connect()
        try:
            for sql in _SCHEMA:
                conn.execute(sql)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(notes)")}
            if "policy_params" not in cols:
                conn.execute("ALTER TABLE notes ADD COLUMN policy_params TEXT")  # NULL = 아직 판정 전, '[]' = 해당 없음
            now = _now()
            for s in SEED:
                row = {f: s.get(f) for f in _FIELDS}
                row["value_text"] = row["value_text"] or ""
                row["source_kind"] = row["source_kind"] or "manual"
                row["note"] = row["note"] or ""
                row["calc"] = row["calc"] or ""
                row["effective_on"] = row["effective_on"] or ""
                conn.execute(f"INSERT OR IGNORE INTO policy_params (key, {', '.join(_FIELDS)}, updated_at) "
                             f"VALUES (?, {', '.join('?' * len(_FIELDS))}, ?)", (s["key"], *row.values(), now))
            conn.commit()
        finally:
            conn.close()
        _ready.add(path)


def _fmt_ym(p: str) -> str:
    return f"{p[:4]}-{p[4:6]}" if re.fullmatch(r"\d{6}", p or "") else p


def refresh_auto() -> dict:
    """자동 항목을 수집 표에서 다시 읽는다. 값이 바뀌었으면 직전 값·바뀐 날을 남긴다."""
    ensure()
    conn = db.connect()
    changed = []
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        found: dict[str, tuple[float, str, float | None, str | None]] = {}
        if "re_base_rate" in names:
            rs = conn.execute("SELECT changed_on, rate FROM re_base_rate ORDER BY changed_on DESC LIMIT 2").fetchall()
            if rs:
                found["base_rate"] = (rs[0]["rate"], rs[0]["changed_on"], rs[1]["rate"] if len(rs) > 1 else None,
                                      rs[0]["changed_on"])
        if "re_econ_series" in names:
            # (항목 키, 계열 id, 배율) — 매달 바뀌는 값이라 배지 대신 '전월 대비'로 보인다
            for key, sid, scale in (("mortgage_rate", "mortgage_new", 1), ("house_outlook_csi", "house_outlook_csi", 1),
                                    ("housing_loan_balance", "housing_loan_balance", 0.001)):  # 십억원 → 조원
                rs = conn.execute("SELECT period, value FROM re_econ_series WHERE series=? AND value IS NOT NULL "
                                  "ORDER BY period DESC LIMIT 2", (sid,)).fetchall()
                if rs:
                    found[key] = (round(rs[0]["value"] * scale, 1 if scale != 1 else 2), _fmt_ym(rs[0]["period"]),
                                  round(rs[1]["value"] * scale, 1 if scale != 1 else 2) if len(rs) > 1 else None, None)
        now = _now()
        for key, (val, eff, prev, changed_on) in found.items():
            cur = conn.execute("SELECT value, effective_on FROM policy_params WHERE key=?", (key,)).fetchone()
            if not cur:
                continue
            if cur["value"] != val or cur["effective_on"] != eff:
                conn.execute("UPDATE policy_params SET value=?, effective_on=?, prev_value=?, changed_on=?, checked_on=?, "
                             "updated_at=? WHERE key=?", (val, eff, prev, changed_on, now[:10], now, key))
                conn.execute("INSERT INTO policy_param_history (key, value, value_text, effective_on, source_url, by, at) "
                             "VALUES (?,?,?,?,?,?,?)", (key, val, "", eff, "", "자동", now))
                changed.append(key)
        conn.commit()
    finally:
        conn.close()
    return {"changed": changed}


def _public(r: dict) -> dict:
    d = {k: r[k] for k in ("key", "grp", "label", "value", "value_text", "unit", "scope", "effective_on", "source_name",
                           "source_url", "source_kind", "note", "calc", "prev_value", "prev_text", "changed_on", "checked_on")}
    d["changed"] = False
    if r.get("changed_on"):
        try:
            d["changed"] = date.fromisoformat(r["changed_on"][:10]) >= date.today() - timedelta(days=CHANGED_DAYS)
        except ValueError:
            pass
    return d


def all_params(include_draft: bool = False) -> list[dict]:
    ensure()
    conn = db.connect()
    try:
        where = "" if include_draft else "WHERE status='published'"
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM policy_params {where} ORDER BY sort, key")]
    finally:
        conn.close()
    if include_draft:
        for r in rows:
            r["changed"] = _public(r)["changed"]
        return rows
    return [_public(r) for r in rows if r["value"] is not None or r["value_text"]]


def public_map() -> dict[str, dict]:
    return {p["key"]: p for p in all_params()}


def update(key: str, fields: dict, by: str = "관리자") -> dict:
    """관리자 수정. 값(value/value_text)이 바뀌면 직전 값·바뀐 날(기준일 또는 오늘)을 남기고 이력에 한 줄."""
    ensure()
    conn = db.connect()
    try:
        cur = conn.execute("SELECT * FROM policy_params WHERE key=?", (key,)).fetchone()
        if not cur:
            raise KeyError(key)
        cur = dict(cur)
        if cur["source_kind"] == "auto":
            fields = {k: v for k, v in fields.items() if k in ("status", "note", "source_name", "source_url", "label", "scope")}
        upd = {k: v for k, v in fields.items() if k in EDITABLE}
        if "status" in upd and upd["status"] not in ("draft", "published"):
            raise ValueError("상태는 draft·published 중 하나입니다.")
        if "value" in upd:
            v = upd["value"]
            upd["value"] = None if v in (None, "") else float(v)
        if "source_url" in upd:
            upd["source_url"] = db.safe_url(upd["source_url"])
        if "effective_on" in upd and upd["effective_on"] and not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", upd["effective_on"]):
            raise ValueError("기준일은 YYYY-MM-DD 형식으로 넣어 주세요.")
        if upd.get("status") == "published":
            v = upd.get("value", cur["value"])
            vt = upd.get("value_text", cur["value_text"])
            src = upd.get("source_url", cur["source_url"])
            if v is None and not vt:
                raise ValueError("값이 없는 항목은 게시할 수 없습니다.")
            if not src:
                raise ValueError("근거 링크가 없는 항목은 게시할 수 없습니다.")
            if not upd.get("effective_on", cur["effective_on"]):  # 2026-11-03 — 기준일 없는 숫자가 공개되지 않게 (운영 기준 '숫자에는 출처·기준일')
                raise ValueError("기준일이 없는 항목은 게시할 수 없습니다. 원문에서 시행일·기준일을 확인해 넣어 주세요.")
        now = _now()
        value_changed = ("value" in upd and upd["value"] != cur["value"]) or \
                        ("value_text" in upd and (upd["value_text"] or "") != (cur["value_text"] or ""))
        if value_changed:
            upd["prev_value"] = cur["value"]
            upd["prev_text"] = cur["value_text"]
            upd["changed_on"] = (upd.get("effective_on") or cur["effective_on"] or now[:10])[:10]
            if len(upd["changed_on"]) == 7:
                upd["changed_on"] += "-01"
        if not upd:
            return dict(cur)
        upd["updated_at"] = now
        conn.execute(f"UPDATE policy_params SET {', '.join(f'{k}=?' for k in upd)} WHERE key=?", (*upd.values(), key))
        if value_changed:
            conn.execute("INSERT INTO policy_param_history (key, value, value_text, effective_on, source_url, by, at) "
                         "VALUES (?,?,?,?,?,?,?)", (key, upd.get("value", cur["value"]), upd.get("value_text", cur["value_text"]),
                                                    upd.get("effective_on", cur["effective_on"]),
                                                    upd.get("source_url", cur["source_url"]), by, now))
        conn.commit()
        return dict(conn.execute("SELECT * FROM policy_params WHERE key=?", (key,)).fetchone())
    finally:
        conn.close()


def history(key: str, limit: int = 30) -> list[dict]:
    ensure()
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM policy_param_history WHERE key=? ORDER BY id DESC LIMIT ?",
                                              (key, limit))]
    finally:
        conn.close()


# ───────────────────────── 노트 연결 ─────────────────────────

def detect_keys(n: dict) -> list[str]:
    text = " ".join(str(n.get(k) or "") for k in ("title", "tags", "summary", "body"))
    out: list[str] = []
    for pat, keys in NOTE_RULES:
        if re.search(pat, text, re.I):
            out += [k for k in keys if k not in out]
    return out


def note_keys(n: dict) -> list[str]:
    try:
        v = json.loads(n.get("policy_params") or "null")
    except (TypeError, ValueError):
        v = None
    return [k for k in v if isinstance(k, str)] if isinstance(v, list) else []


def clean_keys(v) -> str:
    known = {s["key"] for s in SEED}
    return json.dumps([k for k in dict.fromkeys(v or []) if isinstance(k, str) and k in known][:12])


def backfill_notes(force: bool = False) -> dict:
    """policy_params 가 NULL 인 노트를 키워드 규칙으로 채운다."""
    ensure()
    conn = db.connect()
    try:
        where = "" if force else "WHERE policy_params IS NULL"
        rows = [dict(r) for r in conn.execute(f"SELECT id, title, tags, summary, body FROM notes {where}")]
        hit = 0
        with conn:
            for r in rows:
                keys = detect_keys(r)
                hit += bool(keys)
                conn.execute("UPDATE notes SET policy_params=? WHERE id=?", (json.dumps(keys), r["id"]))
        return {"checked": len(rows), "linked": hit}
    finally:
        conn.close()


def notes_for(key: str, limit: int = 3) -> list[dict]:
    """이 항목을 다룬 게시 노트 (최근 순)."""
    ensure()
    conn = db.connect()
    try:
        rows = conn.execute("SELECT id, title, published FROM notes WHERE status='published' AND policy_params LIKE ? "
                            "ORDER BY published DESC, id DESC LIMIT ?", (f'%"{key}"%', limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def for_note(n: dict) -> list[dict]:
    """노트 상세에 붙일 현행 수치 (게시된 항목만)."""
    pm = public_map()
    return [pm[k] for k in note_keys(n) if k in pm]
