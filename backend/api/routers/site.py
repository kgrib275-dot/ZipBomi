"""사이트 공통 — 수치·수집 소스·소개 (/api/site, /api/about).

Streamlit 판 app_pages/home.py(_source_groups·히어로 수치)와 app_pages/about.py(숫자로 보기)를 옮겼다.
"""
from __future__ import annotations


from fastapi import APIRouter

from api.common import cached
from pipeline import db, jobs, privacy, settings_store

router = APIRouter(tags=["site"])



def source_groups() -> dict[str, list[dict]]:
    """소스 그룹 → [{name, url}] (config/sources.yaml, 10분 캐시 — 파일을 매번 읽지 않게)."""
    def build():
        groups: dict[str, list[dict]] = {}
        for s in jobs.config()["sources"]:
            groups.setdefault(s.get("group", "기타"), []).append({"name": s["name"], "url": s.get("site") or s["url"]})
        return groups
    return cached("site:sources", build, 600)


def counts() -> dict:
    def build():
        sources = source_groups()
        return {"notes": len(db.notes()), "articles_week": db.article_count_since(7),
                "sources": sum(len(v) for v in sources.values())}
    return cached("site:counts", build, 60)  # 공개 주소라 매번 세지 않게


@router.get("/site")
def site() -> dict:
    return {"counts": counts(), "sources": source_groups(), "privacy_active": privacy.active(), "newsletter": _newsletter()}


def _newsletter() -> dict:
    """화면의 구독 안내 문구가 쓰는 실제 발송 일정 (관리 > 배치 스케줄, 2026-11-03)."""
    c = settings_store.load().get("newsletter") or {}
    try:
        hh, mm = map(int, str(c.get("time") or "09:00").split(":"))
        day = "월화수목금토일"[int(c.get("weekday") or 0) % 7]
    except ValueError:
        return {"enabled": False, "when": ""}
    ampm = "오전" if hh < 12 else "오후"
    h12 = hh if 1 <= hh <= 12 else (hh - 12 if hh > 12 else 12)
    return {"enabled": bool(c.get("enabled")), "when": f"{day}요일 {ampm} {h12}시" + (f" {mm}분" if mm else "")}


@router.get("/about")
def about() -> dict:
    sources = source_groups()
    conn = db.connect()
    try:
        n_articles = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    finally:
        conn.close()
    c = counts()
    c.update({"articles": n_articles, "issues": len(db.issues("published"))})
    return {"sources": sources, "counts": c}
