"""오늘의 내 브리핑 (2026-11-20) — 홈 맨 위에 '오늘 챙길 것'을 규칙으로 모아 보여 준다. 저장된 표와 내 저장값(visitor_state)만 읽고, LLM·외부 호출은 없다.

카드 순서 = 시급도(오늘 마감·오늘 일정) → 점수. 최대 MAX_CARDS 장. 카드마다 누르면 갈 화면(to)이 있다.
 1. 오늘·내일 일정(내 일정·항목 알림·할 일)   2. 내 지역 접수 중·곧 시작 공고(무순위·재공급 표시)   3. 관심·알림 공고 임박
 4. 내 지역 새 공고(최근 2일)   5. 관심 단지 새 거래(최근 7일)   6. 기준금리 변동   7. 내 가점 vs 지역 당첨 중앙값   8. 전세 만기
"""
from __future__ import annotations

from datetime import date, timedelta

from . import db, profile as profile_mod, pubdata, reminders

MAX_CARDS = 6


def sub_score(p: dict) -> int | None:
    """청약 가점(84점 만점) — 무주택 기간·부양가족·통장 가입 기간 선택지 번호로 계산(계산기와 같은 표). 하나라도 없으면 None."""
    try:
        h, f, a = int(p["sub_home"]), int(p["sub_fam"]), int(p["sub_acct"])
    except (KeyError, TypeError, ValueError):
        return None
    return (0 if h == 0 else 2 * h) + 5 + 5 * f + a + 1


def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _left(d: date | None, today: date) -> int | None:
    return None if d is None else (d - today).days


def _dday(n: int) -> str:
    return "오늘" if n == 0 else f"D-{n}"


def regions_sidos(prof: dict) -> list[str]:
    return sorted({profile_mod._SIDO_OF.get(str(c)) for c in (prof.get("regions") or [])} - {None})


def _notices(sidos: list[str], today: date) -> list[dict]:
    if not sidos:
        return []
    since = (today - timedelta(days=60)).isoformat()
    try:
        c = db.connect()
        try:
            rows = c.execute(f"SELECT notice_id, name, region, house_type, category, receipt_start, receipt_end, notice_date FROM re_apply_notice "
                             f"WHERE region IN ({','.join('?' * len(sidos))}) AND COALESCE(notice_date, receipt_start, '') >= ? ORDER BY notice_date DESC LIMIT 300",
                             (*sidos, since)).fetchall()
            return [dict(r) for r in rows]
        finally:
            c.close()
    except Exception:  # noqa: BLE001 - 표가 없으면 공고 카드만 건너뜀
        return []


def build(st: dict, today: date | None = None) -> dict:
    today = today or date.today()
    prof = st.get("profile") if isinstance(st.get("profile"), dict) else {}
    cards: list[dict] = []

    def add(kind: str, icon: str, title: str, sub: str, to: str, urgent: bool, score: int) -> None:
        cards.append({"kind": kind, "icon": icon, "title": title[:70], "sub": sub[:90], "to": to, "urgent": urgent, "score": score})

    # 1) 오늘·내일 일정
    try:
        rows = reminders.my_rows(st, today)
    except Exception:  # noqa: BLE001
        rows = []
    if rows:
        now = [r for r in rows if r["left"] == 0] or rows
        t = f"{'오늘' if now[0]['left'] == 0 else '내일'} 일정·할 일 {len(now)}건"
        add("my", "📅", t, " · ".join(r["title"] for r in now[:3]) + (f" 외 {len(now) - 3}건" if len(now) > 3 else ""), "/my", any(r["left"] == 0 for r in rows), 90)
    # 2·3·4) 청약 공고
    sidos = regions_sidos(prof)
    seen: set[str] = set()
    favs = {i for i in (prof.get("alert_apply") or []) if isinstance(i, str)}
    notices = _notices(sidos, today)
    tag = lambda n: {"resale": "🔁 재공급", "lottery": "무순위·잔여"}.get(pubdata.supply_kind(n), "")  # noqa: E731
    for n in notices:
        st_d, en_d = _d(n.get("receipt_start")), _d(n.get("receipt_end")) or _d(n.get("receipt_start"))
        if en_d is None or en_d < today or n["notice_id"] in seen:
            continue
        if (en_d - (st_d or en_d)).days > 120:
            continue  # 상시·선착순 공고
        sl, el = _left(st_d, today), _left(en_d, today)
        sup = pubdata.supply_kind(n)
        if sl is not None and sl <= 0 <= el:
            when = "오늘 마감" if el == 0 else f"접수 중 · 마감 D-{el}"
            add("apply", "📋", f"{n['name']} {when}", f"{n['region']} {tag(n)}".strip(), f"/c/{n['notice_id']}", el <= 1, 80 + (6 if sup else 0) + (4 if n['notice_id'] in favs else 0))
        elif sl is not None and 0 < sl <= 7:
            add("apply", "📋", f"{n['name']} 접수 {_dday(sl)}", f"{n['region']} {tag(n)}".strip(), f"/c/{n['notice_id']}", sl <= 1, 70 + (6 if sup else 0) + (4 if n['notice_id'] in favs else 0))
        else:
            continue
        seen.add(n["notice_id"])
    if len([c for c in cards if c["kind"] == "apply"]) > 3:  # 공고 카드는 3장까지
        keep = sorted((c for c in cards if c["kind"] == "apply"), key=lambda c: (-int(c["urgent"]), -c["score"]))[:3]
        cards[:] = [c for c in cards if c["kind"] != "apply"] + keep
    fresh = [n for n in notices if (_d(n.get("notice_date")) or date.min) >= today - timedelta(days=2) and n["notice_id"] not in seen
             and ((_d(n.get("receipt_end")) or _d(n.get("receipt_start")) or date.min) >= today)]
    if fresh:
        add("new", "🆕", f"내 지역 새 청약 공고 {len(fresh)}건", ", ".join(n["name"] for n in fresh[:2]) + (" 외" if len(fresh) > 2 else ""), f"/c/{fresh[0]['notice_id']}" if len(fresh) == 1 else "/calendar", False, 60)
    # 5) 관심 단지 새 거래
    try:
        for _wkey, w, deals in reminders.watch_deals(st.get("re_watch") or [], today)[:6]:
            recent = [d for d in deals if d["date"] and 0 <= (today - date.fromisoformat(d["date"][:10])).days <= 7 and reminders.cond_ok(w, d)]
            if recent:
                top = recent[0]
                add("deal", "🏢", f"{w['apt']} 새 거래 {len(recent)}건", f"마지막 {pubdata.man(top['amount'])} · 전용 {round(top['area'] or 0)}㎡",
                    f"/my-homes?lawd={w['lawd']}&dong={w.get('dong') or ''}&apt={w['apt']}", False, 55)
    except Exception:  # noqa: BLE001
        pass
    # 6) 금리
    try:
        from api.routers import me as me_router
        ra = me_router.rate_alert(st, today)
        if ra:
            add("rate", "📉" if "인하" in ra["title"] else "📈", ra["title"], ra["what"], "/calc?tab=loan", False, 50)
    except Exception:  # noqa: BLE001
        pass
    # 7) 가점 vs 지역 당첨 중앙값
    sc = sub_score(prof)
    if sc is not None and sidos:
        rs = pubdata.region_scores(sidos[0])
        if rs:
            d = round(sc - rs["median"], 1)
            add("score", "📈", f"내 가점 {sc}점 · {rs['region']} 당첨 중앙값 {rs['median']:g}점", f"{'+' if d >= 0 else ''}{d:g}점 (참고용)", "/calendar?tab=scores", False, 40)
    # 8) 전세 만기
    le = _d(prof.get("lease_end"))
    if le and prof.get("type") == "tenant":
        n = _left(le, today)
        if n is not None and 0 <= n <= 120:
            add("lease", "🔑", f"전세 만기 {_dday(n)}", "갱신 요구·이사 준비 일정을 확인해요", "/my", n <= 30, 65)
    cards.sort(key=lambda c: (-int(c["urgent"]), -c["score"]))
    has_profile = bool(prof.get("type") or prof.get("regions") or st.get("re_watch") or st.get("my_events"))
    return {"cards": cards[:MAX_CARDS], "has_profile": has_profile, "regions": regions_sidos(prof), "date": today.isoformat()}
