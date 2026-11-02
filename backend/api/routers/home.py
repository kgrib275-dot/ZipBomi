"""홈 (/api/home) — 이번 주 흐름·꼭 알아야 할 3가지·나를 위한 추천·급상승 띠·최신 노트·수치·소스.

Streamlit 판 app_pages/home.py 를 옮겼다. 본문 강조(editorial.highlight)는 이스케이프된 HTML 이다.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter

from api.common import cached, note_card
from api.deps import Caller, CallerDep
from api.routers import me as me_state
from api.routers.site import counts, source_groups
from app import ax_types
from pipeline import db, editorial, engage, industry, jobs, knowledge, profile, report_pdf
from pipeline.llm import CATEGORIES

router = APIRouter(tags=["home"])


def _trends() -> dict:
    """키워드 일별 추이 — 10분 캐시 (try_it 등에서 쓴다)."""
    return cached("home:trends", knowledge.trends, 600)


def _weekly_growth() -> list[dict]:
    """키워드별 최근 7일 vs 그 전 7일 기사 수 (KST 발행일 기준)."""
    kws = [k for k in db.list_keywords() if k.get("mode") == "include" and k.get("active", True) and k["category"] in CATEGORIES]
    today = datetime.now(db.KST).date()
    cur_from, prev_from = today - timedelta(days=6), today - timedelta(days=13)
    cur = {k["keyword"]: 0 for k in kws}
    prev = dict(cur)
    for a in db.articles(15):
        d = knowledge._day(a)
        if not d or d < prev_from or d > today:
            continue
        bucket = cur if d >= cur_from else prev
        for k in set(json.loads(a["matched_kw"] or "[]")):
            if k in bucket:
                bucket[k] += 1
    rows = []
    for k in kws:
        c, p = cur[k["keyword"]], prev[k["keyword"]]
        if c < 2:  # 한두 건짜리는 증감률이 과장된다
            continue
        growth = None if p == 0 else round((c - p) / p * 100)
        rows.append({"keyword": k["keyword"], "category": k["category"], "cur": c, "prev": p, "growth": growth,
                     "aliases": k.get("aliases") or []})
    # 오른 것 먼저(신규는 이번 주 건수로), 그다음 덜 내린 순
    rows.sort(key=lambda r: (-(r["growth"] if r["growth"] is not None else 10_000 + r["cur"]), -r["cur"]))
    return rows


def _rep_note(keyword: str, aliases: list[str], notes: list[dict], score: dict[str, int]) -> dict | None:
    """키워드(또는 별칭)가 제목·태그·요약에 나오는 가장 최근 게시 노트 — 같은 날이면 원문 기사 점수가 높은 것."""
    words = [w.lower() for w in [keyword, *keyword.split("·"), *aliases] if w and len(w) >= 2]
    hits = [n for n in notes if any(w in f"{n['title']} {n.get('tags') or ''} {n.get('summary') or ''}".lower() for w in words)]
    if not hits:
        return None
    return max(hits, key=lambda n: (n.get("published") or "", score.get(n.get("article_hash") or "", 0), n["id"]))


def ticker() -> dict | None:
    """급상승 키워드 띠 — 지난주 대비 증감률(%)과 대표 노트 링크. 10분 캐시."""
    return cached("home:ticker", _ticker, 600)


def _ticker() -> dict | None:
    rows = _weekly_growth()
    if not rows:
        return None
    notes = db.notes()
    hashes = [n["article_hash"] for n in notes if n.get("article_hash")]
    score = {}
    if hashes:
        conn = db.connect()
        try:
            for i in range(0, len(hashes), 500):
                chunk = hashes[i:i + 500]
                score.update(conn.execute(f"SELECT url_hash, COALESCE(llm_score, 0) FROM articles WHERE url_hash IN ({','.join('?' * len(chunk))})",
                                          chunk).fetchall())
        finally:
            conn.close()
    out = []
    for r in rows[:12]:
        n = _rep_note(r["keyword"], r["aliases"], notes, score)
        out.append({"keyword": r["keyword"], "category": r["category"], "cur": r["cur"], "prev": r["prev"],
                    "growth": r["growth"], "is_new": r["growth"] is None, "rising": r["growth"] is None or r["growth"] > 0,
                    "label": "신규" if r["growth"] is None else f"{'▲' if r['growth'] > 0 else '▼' if r['growth'] < 0 else '–'} {abs(r['growth'])}%",
                    "href": f"/notes?id={n['id']}" if n else f"/notes?q={quote(r['keyword'].split('·')[0])}",
                    "note_title": n["title"] if n else None})
    return {"head": "급상승 키워드 · 지난주 대비", "basis": "최근 7일과 그 전 7일의 기사 수 비교", "rows": out}

def for_you(visitor: str, notes: list[dict]) -> list[dict]:
    """나를 위한 추천 — 이미 이 방문자에게서 받은 정보(연속 참여·진단·유형·관심 지역)로만 만든다."""
    cards = []
    state = me_state.load_state(visitor)
    streak = engage.streak(visitor)
    today_done = len({r["item"] for r in engage.mine("quiz", visitor, engage.today().isoformat() + ":")})
    if streak or today_done:
        left = engage.QUIZ_PER_DAY - today_done
        cards.append({"url": "/today", "kicker": f"🔥 연속 {max(streak, 1)}일째",
                      "title": "오늘 퀴즈 완료 ✓" if left <= 0 else f"오늘 퀴즈 {left}문제 남음"})
    weak = state.get("diag_weak")
    if weak in CATEGORIES:
        n = sum(x["category"] == weak for x in notes)
        cards.append({"url": f"/notes?cat={weak.replace(' ', '+')}", "kicker": "진단에서 가장 약했던 영역", "title": f"{weak} 노트 {n}편"})
    answers = state.get("axt_answers") or []
    if isinstance(answers, list) and len(answers) == len(ax_types.QUESTIONS) and all(isinstance(a, str) for a in answers):
        code, _ = ax_types.score(answers)
        if code in ax_types.TYPES:
            emoji, name, _, _, cat = ax_types.TYPES[code]
            cards.append({"url": f"/notes?cat={cat.replace(' ', '+')}", "kicker": f"{emoji} {name}에게 맞는", "title": f"{cat} 노트"})
    pref = state.get("pref_inds") or []
    for ind in (pref if isinstance(pref, list) else [])[:2]:
        if ind in industry.NAMES:
            cards.append({"url": f"/notes?ind={ind}", "kicker": "구독할 때 고른 관심 지역",
                          "title": f"{ind} 소식 {len(industry.filter_notes(notes, [ind]))}편"})
    return cards[:4]

@router.get("/home/mine")
def home_mine(c: Caller = CallerDep) -> dict:
    """이번 주 나에게 영향 있는 것 3가지 — 프로필(유형·관심 지역)로 최근 14일 게시 노트를 고른다. 프로필이 없으면 has_profile=False."""
    prof = me_state.load_state(c.visitor).get("profile")
    if not isinstance(prof, dict) or not (prof.get("type") or prof.get("regions")):
        return {"has_profile": False, "items": []}
    notes = cached("home:shared", _shared, _SHARED_TTL)["_notes"]
    res = profile.personal_three(notes, prof)
    items = [{**note_card(x["note"]), "reason": x["reason"], "matched": x["matched"]} for x in res["items"]]
    return {"has_profile": True, "items": items, "filled": res["filled"], "matched": res["matched"], "days": res["days"],
            "type": profile.TYPES.get(prof.get("type"), ""), "regions": [profile.short_name(r) for r in prof.get("regions") or []]}


_SHARED_TTL = 30  # 모든 방문자에게 같은 부분은 30초 캐시 — 가장 많이 열리는 화면이라 동시 접속 때 효과가 크다


@router.get("/home")
def home(c: Caller = CallerDep) -> dict:
    shared = cached("home:shared", _shared, _SHARED_TTL)
    out = {k: v for k, v in shared.items() if k != "_notes"}
    out["for_you"] = for_you(c.visitor, shared["_notes"])  # 방문자마다 다른 부분만 매번 계산
    return out


def _shared() -> dict:
    issues = db.issues()
    notes = db.notes()
    current = issues[-1] if issues else {"week": "", "range": "", "headline_em": "", "headline": "첫 주간 흐름을 준비 중입니다",
                                         "body": "", "editor_note": ""}
    note = (current.get("editor_note") or "").strip()
    pdf = report_pdf.report_path(current) if current.get("id") else None
    issue = {
        "id": current.get("id"), "week": current["week"], "range": current["range"], "headline_em": current["headline_em"],
        "headline": current["headline"], "body_html": editorial.highlight(current["body"]),  # **강조** → 형광펜, 관점 주제어 → 색
        "editor_note_html": editorial.highlight(note) if note else "",
        "pdf_url": f"/r/{pdf.name}" if pdf and pdf.exists() else None,
    }
    flow = [{"week": x["week"], "headline_em": x["headline_em"],
             # 흐름 목록에는 콜론 앞 핵심 문구만 보여 준다.
             "headline_short": (x["headline_em"] + " " + x["headline"].split(":")[0]).strip(), "now": i == len(issues) - 1}
            for i, x in enumerate(issues[-5:])]

    # 이번 주 꼭 알아야 할 3가지 — 이번 호 주의 노트에서 관점 점수로 고른다 (pipeline/editorial.py)
    pool = []
    if current.get("week_start"):
        monday, sunday = jobs.week_bounds(date.fromisoformat(current["week_start"]))
        pool = db.notes_published_between(monday.isoformat(), sunday.isoformat())
    three = editorial.leader_three(pool or notes[:10], current.get("picks", ""))
    leader3 = [{"id": t["id"], "title": t["title"], "category": t["category"], "point": t["point"]} for t in three]

    cat_counts = {cat: sum(n["category"] == cat for n in notes) for cat in CATEGORIES}
    return {
        "issue": issue, "issues": flow, "leader3": leader3, "stance": editorial.lens().get("stance", ""),
        "ticker": ticker(), "_notes": notes,  # _notes: 방문자별 for_you 계산용 (응답에서는 뺀다)
        "latest_notes": [note_card(n) for n in notes[:9]],
        "counts": {**counts(), "categories": cat_counts}, "sources": source_groups(),
    }

