"""캘린더 구독 주소 (2026-11-17) — 휴대폰·PC 캘린더 앱에 '구독'으로 넣어 두면 내 공간 일정이 저절로 따라온다.

- GET /cal/<토큰>.ics (접두어 없음, 로그인 없이 캘린더 앱이 주기적으로 받아 감): 로그인 계정의 내 일정(my_events)·항목 알림(my_items)·
  할 일 마감(my_todos)·관심/알림 청약 공고(접수 시작·마감·발표)·전세 만기. 오늘 60일 전부터, 최대 400건. LLM 없음.
- 토큰은 128비트 무작위, DB 에는 해시만 (pipeline/accounts.cal_*). 주소는 만들 때 한 번만 보여 주고, 새로 만들면 예전 주소는 멈춘다.
- GET/POST/DELETE /api/me/cal-feed: 상태·만들기(다시 만들기)·끄기 — 로그인 계정만.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from api.deps import Caller, CallerDep
from pipeline import accounts, mailer, my_space

router = APIRouter(tags=["calendar-feed"])
root_router = APIRouter(tags=["calendar-feed"])

PAST_DAYS = 60
MAX_EVENTS = 400


def _acc(c: Caller) -> dict:
    a = accounts.by_raw(c.raw) if c.visitor.startswith("c:") else None
    if not a:
        raise HTTPException(401, "메일로 로그인한 계정에서만 쓸 수 있어요.")
    return a


def _feed_url(request: Request, token: str) -> str:
    base = (mailer.site_url() or str(request.base_url)).rstrip("/")
    return f"{base}/cal/{token}.ics"


@router.get("/me/cal-feed")
def feed_status(c: Caller = CallerDep) -> dict:
    a = accounts.by_raw(c.raw) if c.visitor.startswith("c:") else None
    if not a:
        return {"account": False, "on": False}
    st = accounts.cal_status(a["id"])
    return {"account": True, "on": bool(st), "created_at": (st or {}).get("created_at"), "last_fetch_at": (st or {}).get("last_fetch_at")}


@router.post("/me/cal-feed")
def feed_create(request: Request, c: Caller = CallerDep) -> dict:
    """새 구독 주소 — 예전 주소는 바로 멈춘다. 주소는 이 응답에서만 보여 준다."""
    a = _acc(c)
    url = _feed_url(request, accounts.cal_create(a["id"]))
    return {"on": True, "url": url, "webcal": "webcal://" + url.split("://", 1)[-1]}


@router.delete("/me/cal-feed")
def feed_off(c: Caller = CallerDep) -> dict:
    accounts.cal_off(_acc(c)["id"])
    return {"on": False}


# ───────────────────────── iCalendar 만들기 ─────────────────────────

def _esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """75바이트(UTF-8)를 넘는 줄은 다음 줄을 공백으로 시작 — 한글이 깨지지 않게 글자 단위로 자른다."""
    if len(line.encode()) <= 75:
        return line
    parts, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode())
        if size + n > (74 if parts else 75):
            parts.append(cur)
            cur, size = "", 0
        cur += ch
        size += n
    parts.append(cur)
    return "\r\n ".join(parts)


def _d(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def events_for(state: dict, today: date | None = None) -> list[dict]:
    """계정 저장값 → [{uid, date, title, desc, url}] (날짜순)."""
    today = today or date.today()
    floor = today - timedelta(days=PAST_DAYS)
    out: list[dict] = []

    def add(uid: str, when, title: str, desc: str = "", url: str = "") -> None:
        d = _d(when)
        if d and d >= floor:
            out.append({"uid": uid, "date": d, "title": str(title)[:120], "desc": str(desc)[:500], "url": url})

    for ev in state.get("my_events") or [] if isinstance(state.get("my_events"), list) else []:
        if isinstance(ev, dict):
            add(f"ev-{ev.get('id')}", ev.get("date"), f"[일정] {ev.get('title') or '내 일정'}", ev.get("memo") or "")
    for key, v in (state.get("my_items") or {}).items() if isinstance(state.get("my_items"), dict) else []:
        if isinstance(v, dict) and v.get("remind"):
            add("it-" + hashlib.sha1(str(key).encode()).hexdigest()[:12], v["remind"], f"[알림] {v.get('title') or '내 항목'}",
                " · ".join(x for x in (v.get("remind_note"), v.get("memo")) if x))
    for td in state.get("my_todos") or [] if isinstance(state.get("my_todos"), list) else []:
        if isinstance(td, dict) and td.get("due") and not td.get("done"):
            add(f"td-{td.get('id')}", td["due"], f"[할 일] {td.get('text') or ''}")
    prof = state.get("profile") if isinstance(state.get("profile"), dict) else {}
    alerts = prof.get("alert_apply") if isinstance(prof.get("alert_apply"), list) else []
    fav = state.get("apply_fav") if isinstance(state.get("apply_fav"), list) else []
    for n in my_space.notices(list(dict.fromkeys([*alerts, *fav]))):
        url = n.get("url") if str(n.get("url") or "").startswith("http") else ""
        region = f" ({n['region']})" if n.get("region") else ""
        for col, label in (("receipt_start", "접수 시작"), ("receipt_end", "접수 마감"), ("winner_date", "당첨 발표")):
            add(f"ap-{n['notice_id']}-{col}", n.get(col), f"[청약 {label}] {n.get('name') or ''}{region}", "청약홈·LH 공고문으로 자격과 일정을 꼭 확인하세요.", url)
    if prof.get("lease_end"):
        add("lease", prof["lease_end"], "[전세 만기] 내 전세 계약 만기일")
    out.sort(key=lambda e: e["date"])
    return out[:MAX_EVENTS]


def build_ics(events: list[dict], site: str) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ZIPBOMI//My Calendar Feed//KO", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:집보미 내 일정", "X-WR-TIMEZONE:Asia/Seoul", "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for e in events:
        d = e["date"]
        lines += ["BEGIN:VEVENT", f"UID:{e['uid']}@zipbomi", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
                  f"SUMMARY:{_esc(e['title'])}"]
        desc = "\n".join(x for x in (e["desc"], f"집보미 내 공간: {site}/my") if x)
        lines.append(f"DESCRIPTION:{_esc(desc)}")
        if e["url"]:
            lines.append(f"URL:{e['url']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


@root_router.get("/cal/{name}", include_in_schema=False)
def feed(name: str, request: Request) -> Response:
    """캘린더 앱이 받아 가는 주소. 틀리거나 멈춘 주소는 404 (있는지 없는지 구분해 주지 않는다)."""
    from api.routers.me import load_state  # 순환 import 피하기
    token = name[:-4] if name.endswith(".ics") else name
    acc = accounts.cal_account(token)
    if not acc:
        return Response("Not Found", status_code=404, media_type="text/plain", headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})
    site = (mailer.site_url() or str(request.base_url)).rstrip("/")
    body = build_ics(events_for(load_state("c:" + acc["raw"])), site)
    return Response(body, media_type="text/calendar; charset=utf-8", headers={
        "Cache-Control": "private, max-age=900", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer",
        "Content-Disposition": 'inline; filename="zipbomi.ics"'})
