"""내 프로필 (/me) — 로그인 없이 쓰는 개인화의 기준값과, 노트의 시군구(regions)·대상 유형(audience) 판정.

저장 위치 (2026-11-02 Phase 1 결정)
- 기본: 방문자 상태 visitor_state 의 'profile' 키 (쿠키 zgv 기준, 본인 브라우저만) + 브라우저 localStorage 사본.
- 구독자: 확인된 구독자(subscribers.visitor 로 이 브라우저와 이어진 경우)는 subscriber_profile(email PK) 에 사본을 둔다.
  쿠키가 바뀌거나 지워져도 뉴스레터 개인화(나중 단계)가 구독 이메일 기준으로 읽을 수 있게 — visitor_state 는 방문자 쿠키가
  바뀌면 끊기므로 이메일 키 테이블을 따로 두었다. 해지·삭제·'내 기록 지우기' 때 함께 지운다.
- 쓰는 시점: 프로필 저장(PUT /me/state 의 profile), 구독 확인(/subscribe/confirm), 질문하기 연결 링크(/ask/link).

노트 쪽
- notes.regions: 시군구 코드(regions_kr.NAMES 의 5자리) JSON 배열 — 노트 초안 프롬프트가 시군구 이름을 내면 코드로 바꾸고,
  예전 노트는 지명 키워드(regions_kr 이름 + industry.py 지명)로 채운다 (LLM 호출 없음).
- notes.audience: 유형 키 JSON 배열 (first_home / upgrade / tenant / investor) — 기존 audiences 글자에서 옮긴다.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from . import db, industry, regions_kr

# 유형 — 화면 표기 순서 그대로
TYPES: dict[str, str] = {"first_home": "무주택(첫 집)", "upgrade": "1주택 갈아타기", "tenant": "임차인(전월세)", "investor": "투자 관심"}
SHORT: dict[str, str] = {"first_home": "무주택", "upgrade": "갈아타기", "tenant": "임차인", "investor": "투자"}
# 노트의 대상 독자 글자(llm.AUDIENCES) → 유형 키. 중개·실무자는 어느 유형에도 넣지 않는다.
AUDIENCE_MAP: dict[str, str] = {"무주택 실수요자": "first_home", "1주택 갈아타기": "upgrade", "임차인(전월세)": "tenant",
                                "다주택·투자자": "investor", "임대인": "investor"}
MAX_REGIONS = 3
_MAX_MAN = 10_000_000  # 만원 (1천억) — 입력 실수 방지 상한


# ───────────────────────── 프로필 정리 ─────────────────────────

def _int(v, lo: int, hi: int) -> int | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))


def _s(v, n: int = 40) -> str:
    return str(v or "").strip()[:n]


def _test(v, keys: dict[str, int]) -> dict | None:
    """테스트 결과 요약 — 정해진 키만, 문자열은 짧게, 숫자는 0~100."""
    if not isinstance(v, dict):
        return None
    out = {}
    for k, kind in keys.items():
        x = v.get(k)
        if kind == 0 and x not in (None, ""):
            out[k] = _s(x, 40)
        elif kind == 1 and _int(x, 0, 100) is not None:
            out[k] = _int(x, 0, 100)
    at = _s(v.get("at"), 10)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", at):
        out["at"] = at
    return out or None


_TEST_KEYS = {
    "type16": {"code": 0, "name": 0, "emoji": 0},
    "diagnosis": {"score": 1, "level": 0, "weak": 0},
    "career": {"code": 0, "name": 0, "emoji": 0},
    "habit": {"name": 0, "score": 1, "emoji": 0},
}


def clean(p) -> dict | None:
    """화면이 보낸 프로필을 허용한 키·범위로만 남긴다. 남는 값이 없으면 None."""
    if not isinstance(p, dict):
        return None
    out: dict = {}
    if p.get("type") in TYPES:
        out["type"] = p["type"]
    regions = p.get("regions")
    if isinstance(regions, list):
        seen = []
        for r in regions:
            if isinstance(r, str) and r in regions_kr.NAMES and r not in seen:
                seen.append(r)
        if seen:
            out["regions"] = seen[:MAX_REGIONS]
    for k in ("budget_min", "budget_max", "income", "debt"):
        n = _int(p.get(k), 0, _MAX_MAN)
        if n is not None:
            out[k] = n
    if "budget_min" in out and "budget_max" in out and out["budget_min"] > out["budget_max"]:
        out["budget_min"], out["budget_max"] = out["budget_max"], out["budget_min"]
    # 청약 가점 항목 — 계산기(/calc) 선택지 번호와 같다 (무주택 0~16, 부양가족 0~6, 통장 0~16)
    for k, hi in (("sub_home", 16), ("sub_fam", 6), ("sub_acct", 16)):
        n = _int(p.get(k), 0, hi)
        if n is not None:
            out[k] = n
    lease = _s(p.get("lease_end"), 10)
    if out.get("type") == "tenant" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", lease):
        try:
            date.fromisoformat(lease)
            out["lease_end"] = lease
        except ValueError:
            pass
    # 알림 메일 (pipeline/reminders.py) — 구독자에게만 실제로 나간다. 전세 만기 알림은 만기일이 있을 때만 의미가 있다.
    if p.get("alert_lease") is True and "lease_end" in out:
        out["alert_lease"] = True
    ids = p.get("alert_apply")
    if isinstance(ids, list):
        keep = [i for i in dict.fromkeys(ids) if isinstance(i, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,48}", i)][:20]
        if keep:
            out["alert_apply"] = keep
    tests = p.get("tests")
    if isinstance(tests, dict):
        t = {k: c for k, keys in _TEST_KEYS.items() if (c := _test(tests.get(k), keys))}
        if t:
            out["tests"] = t
    if not out:
        return None
    out["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return out


# ───────────────────────── 구독자 사본 (subscriber_profile) ─────────────────────────

_SQL = "CREATE TABLE IF NOT EXISTS subscriber_profile (email TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
_ready: list = []


def _conn():
    conn = db.connect()
    if not _ready:
        conn.execute(_SQL)
        _ready.append(True)
    return conn


def ensure_table() -> None:
    conn = _conn()
    conn.close()


def save_for_subscriber(email: str, profile: dict | None) -> bool:
    """구독자 사본 저장(profile 이 None 이면 삭제). 썼으면 True."""
    conn = _conn()
    try:
        with conn:
            if not profile:
                return conn.execute("DELETE FROM subscriber_profile WHERE email = ?", (email,)).rowcount > 0
            conn.execute("INSERT INTO subscriber_profile (email, data, updated_at) VALUES (?,?,?) "
                         "ON CONFLICT(email) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                         (email, json.dumps(profile, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
            return True
    finally:
        conn.close()


def for_subscriber(email: str) -> dict | None:
    """뉴스레터 개인화가 읽는 곳 (다음 단계에서 mailer 가 쓴다)."""
    conn = _conn()
    try:
        row = conn.execute("SELECT data FROM subscriber_profile WHERE email = ?", (email,)).fetchone()
    finally:
        conn.close()
    try:
        return json.loads(row["data"]) if row else None
    except ValueError:
        return None


def delete_for_subscriber(email: str) -> None:
    save_for_subscriber(email, None)


def sync_visitor(visitor: str, profile: dict | None = None, *, load: bool = False, watch: list | None = None) -> str | None:
    """이 브라우저가 확인된 구독자와 이어져 있으면 구독자 사본을 맞춘다. load=True 면 방문자 상태에서 프로필·관심 단지를 읽는다.
    사본 = 프로필 + 'watch'(관심 단지 목록, Phase 2 — 뉴스레터 '내 관심 단지' 블록용). 맞춘 구독자 이메일을 돌려준다 (없으면 None)."""
    sub = db.subscriber_by_visitor(visitor) if visitor else None
    if not sub:
        return None
    if load or watch is None:
        from api.routers import me as me_state  # 순환 import 피하려고 안에서
        st = me_state.load_state(visitor)
        if load:
            profile = st.get("profile")
        if watch is None:
            watch = st.get("re_watch")
    data = dict(profile) if isinstance(profile, dict) else {}
    w = clean_watch(watch)
    if w:
        data["watch"] = w
    save_for_subscriber(sub["email"], data or None)
    return sub["email"]


# ───────────────────────── 관심 단지 (visitor_state 're_watch') ─────────────────────────

MAX_WATCH = 50


def clean_watch(items) -> list[dict]:
    """관심 목록 항목 {lawd, region, dong, apt, jibun?, area_band?, note, added} — 허용 키·길이만. 지역만 담은 항목은 apt="" ."""
    out: list[dict] = []
    seen = set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        lawd = str(it.get("lawd") or "")
        if lawd not in regions_kr.NAMES:
            continue
        x = {"lawd": lawd, "region": _s(it.get("region"), 30) or regions_kr.NAMES[lawd], "dong": _s(it.get("dong"), 20),
             "apt": _s(it.get("apt"), 60), "note": _s(it.get("note"), 200)}
        jb = _s(it.get("jibun"), 20)
        if jb:
            x["jibun"] = jb
        if it.get("area_band") in ("s", "m", "l"):
            x["area_band"] = it["area_band"]
        added = _s(it.get("added"), 10)
        x["added"] = added if re.fullmatch(r"\d{4}-\d{2}-\d{2}", added) else ""
        key = (x["lawd"], x["dong"], x["apt"])
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out[-MAX_WATCH:]


# ───────────────────────── 노트의 시군구·유형 판정 ─────────────────────────

_SIDO_OF: dict[str, str] = {code: sido for sido, items in regions_kr.REGIONS for code, _ in items}
# 시도 → 노트 지역(industry.py 권역)
_ZONE = {"서울": "서울", "경기": "경기", "인천": "인천", "부산": "부산·울산·경남", "울산": "부산·울산·경남",
         "대구": "대구·경북", "대전": "대전·세종·충청", "세종": "대전·세종·충청", "광주": "광주·전라"}
# 다른 시도에 같은 이름이 있는 구 — 시도 이름이 바로 앞에 올 때만 인정한다
_AMBIGUOUS = {name for name in {n for _, items in regions_kr.REGIONS for _, n in items}
              if sum(n == name for _, items in regions_kr.REGIONS for _, n in items) > 1}
# 이름만 떼면 일상어와 겹치는 줄임말 — '구·시·군'을 붙인 이름만 인정한다 (예: '수정'·'동안'·'수지'·'사상'·'연수')
_RISKY_STEMS = {"동작", "연수", "구리", "수영", "사상", "기장", "유성", "광산", "수정", "수지", "동안", "남동", "중원", "소사",
                "오정", "장안", "단원", "상록", "광주", "강서", "대덕", "북구", "남구", "서구", "동구", "중구", "달성", "울주", "세종",
                "이천", "고양"}
# 다른 뜻으로 더 자주 쓰이는 정식 이름 — 시도를 붙였을 때만 (예: '광주시'는 기사에서 대개 광주광역시)
_SIDO_ONLY = {"광주시"}
# 생활권 지명 → 시군구 (industry.py 의 지명 중 regions_kr 에 코드가 있는 것)
_PLACES: dict[str, list[str]] = {
    "압구정": ["11680"], "반포": ["11650"], "잠실": ["11710"], "목동": ["11470"], "여의도": ["11560"], "성수": ["11200"],
    "한남": ["11170"], "마용성": ["11440", "11170", "11200"], "노도강": ["11350", "11320", "11305"],
    "금관구": ["11545", "11620", "11530"], "강남3구": ["11680", "11650", "11710"], "강남 3구": ["11680", "11650", "11710"],
    "분당": ["41135"], "판교": ["41135"], "일산": ["41285", "41287"], "평촌": ["41173"], "광교": ["41117", "41465"],
    "위례": ["11710", "41131", "41450"], "송도": ["28185"], "해운대": ["26350"], "센텀": ["26350"], "서울 강서": ["11500"],
    "강서구": ["11500"], "세종시": ["36110"], "세종특별자치시": ["36110"], "경기 광주": ["41610"], "경기도 광주": ["41610"],
    "문래": ["11560"], "둔촌": ["11740"], "개포": ["11680"], "대치": ["11680"], "도곡": ["11680"], "청담": ["11680"],
    "방배": ["11650"], "상계": ["11350"], "중계": ["11350"], "마곡": ["11500"], "흑석": ["11590"], "아현": ["11440"],
}


def _aliases() -> list[tuple[str, list[str], bool]]:
    """(지명, 코드들, 정식 이름인지) — 긴 지명부터 (짧은 이름이 긴 이름 안에서 먼저 잡히지 않게)."""
    out: dict[str, tuple[list[str], bool]] = {}

    def add(word: str, codes: list[str], full: bool):
        cur = out.get(word)
        if cur:
            out[word] = (sorted(set(cur[0]) | set(codes)), cur[1] or full)
        else:
            out[word] = (codes, full)

    city_codes: dict[str, list[str]] = {}
    for sido, items in regions_kr.REGIONS:
        for code, name in items:
            parts = name.split()
            gu = parts[-1]
            if len(parts) == 2:  # '수원시 영통구' → 시 단위 언급은 그 시의 모든 구
                city_codes.setdefault(parts[0], []).append(code)
                add(name, [code], True)
            add(f"{sido} {gu}", [code], True)
            if gu not in _AMBIGUOUS and gu not in _SIDO_ONLY:
                add(gu, [code], True)
                stem = re.sub(r"(구|시|군)$", "", gu)
                if len(stem) >= 2 and stem not in _RISKY_STEMS and stem != gu:
                    add(stem, [code], False)
    for city, codes in city_codes.items():
        add(city, codes, True)
        stem = city[:-1]
        if len(stem) >= 2 and stem not in _RISKY_STEMS:
            add(stem, codes, False)
    for w, codes in _PLACES.items():
        # 동네 이름(반포·센텀)은 줄임말처럼 다룬다 — 앞에 한글이 붙으면(단지 이름 '…더휴센텀') 세지 않고, 본문은 두 번 나와야 인정
        add(w, codes, w.endswith(("구", "시")) or " " in w or w in ("마용성", "노도강", "금관구"))
    return sorted(((w, c, f) for w, (c, f) in out.items()), key=lambda x: -len(x[0]))


_ALIAS = _aliases()
_ALIAS_RE = re.compile("|".join(re.escape(w) for w, _, _ in _ALIAS))
_ALIAS_BY = {w: (c, f) for w, c, f in _ALIAS}


def regions_from_text(head: str, body: str = "") -> list[str]:
    """제목·태그·요약(head)과 본문에서 시군구 코드를 찾는다.
    점수: 정식 이름(마포구·수원시) 2, 줄임말(마포) 1, head 안이면 두 배 — 2점 이상인 코드만 (본문에서 지나가는 줄임말 한 번은 빼기)."""
    score: dict[str, float] = {}
    for text, mult in ((head or "", 2), (body or "", 1)):
        for m in _ALIAS_RE.finditer(text):
            codes, full = _ALIAS_BY[m.group(0)]
            # 앞뒤가 한글로 바로 이어지면 다른 낱말의 일부 (예: '마포대교'는 괜찮지만 '부평등'… 은 드묾 — 앞 글자만 본다)
            if m.start() > 0 and re.match(r"[가-힣]", text[m.start() - 1]) and not full:
                continue
            for c in codes:
                score[c] = score.get(c, 0) + (2 if full else 1) * mult
    return sorted((c for c, s in score.items() if s >= 2), key=lambda c: -score[c])[:12]


def regions_from_names(names) -> list[str]:
    """프롬프트가 낸 시군구 이름('서울 마포구', '성남시 분당구', '마포구') → 코드. 모르는 이름은 버린다."""
    out: list[str] = []
    for raw in names if isinstance(names, list) else []:
        name = " ".join(str(raw or "").split())
        if not name:
            continue
        hit = [c for c, full in regions_kr.NAMES.items() if full == name or full.endswith(" " + name) or full.split(" ", 1)[1] == name]
        if len(hit) > 1:  # '중구'처럼 여러 곳 — 시도가 없으면 버린다
            hit = []
        if not hit:
            hit = regions_from_text(name)[:3]
        for c in hit:
            if c not in out:
                out.append(c)
    return out[:12]


def audience_from_text(audiences: str) -> list[str]:
    out: list[str] = []
    for a in (audiences or "").split(","):
        k = AUDIENCE_MAP.get(a.strip())
        if k and k not in out:
            out.append(k)
    return out


def audience_clean(keys) -> list[str]:
    return [k for k in TYPES if isinstance(keys, list) and k in keys]


def note_regions(n: dict) -> list[str]:
    try:
        v = json.loads(n.get("regions") or "[]")
    except (TypeError, ValueError):
        return []
    return [c for c in v if isinstance(c, str) and c in regions_kr.NAMES] if isinstance(v, list) else []


def note_audience(n: dict) -> list[str]:
    raw = n.get("audience")
    if raw is None:  # 아직 채우지 않은 노트 — 글자에서 바로
        return audience_from_text(n.get("audiences") or "")
    try:
        v = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return audience_clean(v)


def detect(n: dict) -> tuple[list[str], list[str]]:
    head = f"{n.get('title', '')} {n.get('tags', '')} {n.get('summary', '')}"
    return regions_from_text(head, n.get("body") or ""), audience_from_text(n.get("audiences") or "")


def backfill_notes(force: bool = False) -> dict:
    """regions·audience 가 비어 있는(NULL) 노트를 키워드·글자 규칙으로 채운다 (LLM 호출 없음). force=True 면 전부 다시."""
    conn = db.connect()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(notes)")}
        if not {"regions", "audience"} <= cols:
            return {"checked": 0, "regions": 0, "audience": 0}
        where = "" if force else "WHERE regions IS NULL OR audience IS NULL"
        rows = [dict(r) for r in conn.execute(f"SELECT id, title, tags, summary, body, audiences, regions, audience FROM notes {where}")]
        n_reg = n_aud = 0
        with conn:
            for r in rows:
                reg, aud = detect(r)
                new_reg = r["regions"] if (r["regions"] is not None and not force) else json.dumps(reg)
                new_aud = r["audience"] if (r["audience"] is not None and not force) else json.dumps(aud)
                conn.execute("UPDATE notes SET regions = ?, audience = ? WHERE id = ?", (new_reg, new_aud, r["id"]))
                n_reg += bool(json.loads(new_reg or "[]"))
                n_aud += bool(json.loads(new_aud or "[]"))
        return {"checked": len(rows), "regions": n_reg, "audience": n_aud}
    finally:
        conn.close()


# ───────────────────────── 개인화: 노트 고르기 ─────────────────────────

def zone_of(code: str) -> str:
    return _ZONE.get(_SIDO_OF.get(code, ""), "")


def short_name(code: str) -> str:
    """'서울 마포구' → '마포구', '경기 성남시 분당구' → '분당구'."""
    return regions_kr.NAMES.get(code, code).split()[-1]


# 유형별 분류 가중치 (청약은 무주택, 시세·정책은 갈아타기·투자, 임대차 정책은 임차인)
CAT_WEIGHT = {
    "first_home": {"청약·분양·개발": 1.0, "정책·세금·대출": 0.9, "시장·시세": 0.5},
    "upgrade": {"시장·시세": 1.0, "정책·세금·대출": 0.9, "청약·분양·개발": 0.5},
    "tenant": {"정책·세금·대출": 1.0, "시장·시세": 0.7, "청약·분양·개발": 0.6},
    "investor": {"시장·시세": 1.0, "정책·세금·대출": 0.9, "청약·분양·개발": 0.8},
}


def match(n: dict, prof: dict) -> dict:
    """노트 하나가 프로필과 얼마나 맞는지 — {type, regions(겹친 코드), zone(겹친 권역), score}."""
    ptype = prof.get("type")
    pregs = [r for r in prof.get("regions") or [] if r in regions_kr.NAMES]
    aud = note_audience(n)
    nregs = note_regions(n)
    type_hit = bool(ptype and ptype in aud)
    reg_hit = [r for r in pregs if r in nregs]
    zones = {zone_of(r) for r in pregs} - {""}
    zone_hit = sorted(zones & set(industry.of(n))) if not reg_hit else []
    return {"type": type_hit, "regions": reg_hit, "zone": zone_hit, "aud": aud, "nregs": nregs}


def mine_ok(n: dict, prof: dict) -> bool:
    """'내 조건에 맞는 노트만' — 유형이 맞고(노트 대상이 비어 있으면 통과), 지역이 맞거나 전국 단위(시군구·권역 없음)."""
    m = match(n, prof)
    if prof.get("type") and m["aud"] and not m["type"]:
        return False
    if not prof.get("regions"):
        return True
    national = not m["nregs"] and not industry.of(n)
    return bool(m["regions"] or m["zone"] or national)


def _days_ago(published: str, today: date) -> int:
    try:
        return max(0, (today - date.fromisoformat((published or "")[:10])).days)
    except ValueError:
        return 99


def personal_three(notes: list[dict], prof: dict, days: int = 14, k: int = 3) -> dict:
    """이번 주 나에게 영향 있는 것 3가지 — 최근 days일 게시 노트를 유형·지역·최신·분류 가중치로 채점.
    맞는 노트가 k편보다 적으면 최신 노트로 채우고 filled=True."""
    today = date.today()
    since = today - timedelta(days=days)
    ptype = prof.get("type")
    cw = CAT_WEIGHT.get(ptype, {})
    scored = []
    for n in notes:
        d = _days_ago(n.get("published"), today)
        if d > days:
            continue
        m = match(n, prof)
        if not (m["type"] or m["regions"] or m["zone"]):
            continue
        s = (4.0 * len(m["regions"][:2])) + (1.5 if m["zone"] else 0) + (3.0 if m["type"] else 0)
        s += 2.0 * (days - d) / days + cw.get(n.get("category"), 0.5)
        reasons = []
        if m["regions"]:
            reasons.append(f"관심 지역 {'·'.join(short_name(r) for r in m['regions'][:2])} 언급")
        elif m["zone"]:
            reasons.append(f"{m['zone'][0]} 소식")
        if m["type"]:
            reasons.append(f"{SHORT[ptype]} 대상")
        scored.append((s, n, " · ".join(reasons)))
    scored.sort(key=lambda x: (-x[0], x[1].get("published") or "", -x[1]["id"]))
    picked = [{"note": n, "reason": r, "matched": True} for _, n, r in scored[:k]]
    filled = len(picked) < k
    if filled:
        have = {p["note"]["id"] for p in picked}
        for n in notes:  # notes 는 최신순
            if len(picked) >= k:
                break
            if n["id"] not in have:
                picked.append({"note": n, "reason": "최신 노트", "matched": False})
    return {"items": picked, "filled": filled, "matched": len(scored), "days": days, "since": since.isoformat()}


# ───────────────────────── 노트 상세: 나에게 미치는 영향 ─────────────────────────

_IMPACT_HEAD = "나에게 미치는 영향"
_SUB_KEYS = (("무주택", "first_home"), ("첫 집", "first_home"), ("갈아타", "upgrade"), ("1주택", "upgrade"),
             ("임차", "tenant"), ("전월세", "tenant"), ("세입자", "tenant"), ("투자", "investor"), ("다주택", "investor"))
_OLD_SECTIONS = {"실수요자 체크리스트": "first_home", "투자자 관점": "investor"}


def _sub_key(label: str) -> str | None:
    return next((k for w, k in _SUB_KEYS if w in label), None)


def split_impact(body: str) -> tuple[str, list[dict]]:
    """본문을 (영향 섹션을 뺀 본문, [{key, label, md}]) 로 나눈다.
    새 형식: '### 나에게 미치는 영향' 아래 '#### 무주택' 등 유형별 소제목.
    예전 형식: '### 실수요자 체크리스트' → 무주택, '### 투자자 관점' → 투자 (그 밖의 유형은 없음)."""
    parts = re.split(r"(?m)^(###\s+.+)$", body or "")
    keep, blocks = [parts[0]], []
    for i in range(1, len(parts), 2):
        head, text = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        title = head.lstrip("#").strip()
        if title.startswith(_IMPACT_HEAD) or title in _OLD_SECTIONS:
            if title in _OLD_SECTIONS:
                key = _OLD_SECTIONS[title]
                blocks.append({"key": key, "label": TYPES[key], "md": text.strip(), "from": title})
                continue
            sub = re.split(r"(?m)^####\s+(.+)$", text)
            for j in range(1, len(sub), 2):
                key = _sub_key(sub[j])
                md = sub[j + 1].strip() if j + 1 < len(sub) else ""
                if key and md and not any(b["key"] == key for b in blocks):
                    blocks.append({"key": key, "label": TYPES[key], "md": md, "from": sub[j].strip()})
            if not blocks and text.strip():  # 소제목 없이 쓴 영향 섹션 — 나누지 않고 본문에 둔다
                keep += [head, text]
            continue
        keep += [head, text]
    order = list(TYPES)
    blocks.sort(key=lambda b: order.index(b["key"]))
    return "".join(keep).strip(), blocks
