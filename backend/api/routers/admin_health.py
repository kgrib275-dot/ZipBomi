"""관리 > 수집 건강 (2026-11-20) — 수집·알림이 빠짐없이 도는지 한 화면에서 본다. 읽기 전용, LLM 없음.

- 서비스 가동: 예약 확인(tick)이 살아 있는지, 꺼져 있던 구간(service_gaps)과 가동률.
- 배치별: 마지막 성공·실패, 지난 14일 날짜별 성공 여부, 놓친 날 수, 다음 예정 시각.
- 부동산 데이터: re_dataset_state — 정상 / 설정 필요(활용신청·꺼짐) / 오류, 오래된 성공.
- 청약 공고: 지난 3주 공고일별 건수(청약홈·LH), 평일에 연속으로 0건이면 경고.
- 뉴스 소스: 지난 7일 vs 그 전 7일 — 갑자기 0건이 된 소스.
- 맨 위 요약(level·reasons)은 위를 규칙으로 합친 것이다.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends

from api.deps import require_admin
from pipeline import alerts, db, scheduler, settings_store

router = APIRouter(prefix="/admin", tags=["admin-health"], dependencies=[Depends(require_admin)])
OK, WARN, BAD = "ok", "warn", "bad"
STALE_HOURS = 36
WEEKLY = scheduler.WEEKLY


def _q(sql: str, args: tuple = ()) -> list[tuple]:
    try:
        c = db.connect()
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()
    except Exception:  # noqa: BLE001 - 표가 아직 없으면 빈 결과
        return []


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def next_run(c: dict, now: datetime, weekly: bool) -> str | None:
    """다음 예정 시각 'YYYY-MM-DD HH:MM' (없으면 None)."""
    try:
        if weekly:
            hh, mm = map(int, str(c["time"]).split(":"))
            for add in range(0, 8):
                d = (now + timedelta(days=add)).date()
                at = datetime.combine(d, datetime.min.time()).replace(hour=hh, minute=mm)
                if d.weekday() == int(c["weekday"]) and at > now:
                    return at.strftime("%Y-%m-%d %H:%M")
            return None
        slots = []
        for hhmm in c.get("times") or []:
            hh, mm = map(int, str(hhmm).split(":"))
            for add in (0, 1):
                at = datetime.combine((now + timedelta(days=add)).date(), datetime.min.time()).replace(hour=hh, minute=mm)
                if at > now:
                    slots.append(at)
        return min(slots).strftime("%Y-%m-%d %H:%M") if slots else None
    except (KeyError, ValueError, TypeError):
        return None


def jobs_section(cfg: dict, now: datetime) -> list[dict]:
    out = []
    since = _iso(datetime.combine((now - timedelta(days=13)).date(), datetime.min.time()))
    for kind, key in list(scheduler.DAILY) + [(k, k) for k in WEEKLY]:
        c = cfg.get(key) or {}
        weekly = kind in WEEKLY
        last_ok = _q("SELECT started_at FROM run_logs WHERE kind=? AND ok=1 ORDER BY started_at DESC, id DESC LIMIT 1", (kind,))
        last = _q("SELECT started_at, ok, message FROM run_logs WHERE kind=? ORDER BY started_at DESC, id DESC LIMIT 1", (kind,))
        by_day = {r[0]: (r[1], r[2]) for r in _q("SELECT substr(started_at,1,10), SUM(ok=1), SUM(ok=0) FROM run_logs WHERE kind=? AND started_at>=? GROUP BY 1", (kind, since))}
        days = []
        for i in range(13, -1, -1):
            d = (now - timedelta(days=i)).date().isoformat()
            ok_n, fail_n = by_day.get(d, (0, 0))
            days.append({"date": d, "ok": int(ok_n or 0), "fail": int(fail_n or 0)})
        missed = 0
        if c.get("enabled") and not weekly:
            for x in days:
                d = date.fromisoformat(x["date"])
                first = min(c.get("times") or ["23:59"])
                before_first = d == now.date() and now.strftime("%H:%M") < first
                if not before_first and not x["ok"]:
                    missed += 1
        out.append({"kind": kind, "label": alerts.LABELS.get(kind, kind), "enabled": bool(c.get("enabled")), "weekly": weekly,
                    "schedule": (f"매주 {'월화수목금토일'[int(c.get('weekday', 0))]} {c.get('time', '')}" if weekly else " · ".join(c.get("times") or [])),
                    "last_ok": last_ok[0][0] if last_ok else None, "last_run": last[0][0] if last else None,
                    "last_failed": bool(last and not last[0][1]), "last_message": (last[0][2] or "")[:120] if last and not last[0][1] else "",
                    "days": days, "missed_days": missed, "next": next_run(c, now, weekly) if c.get("enabled") else None})
    return out


def service_section(now: datetime) -> dict:
    tick = None
    try:
        tick = db.get_meta("scheduler_tick")
    except Exception:  # noqa: BLE001
        pass
    age = None
    try:
        age = int((now - datetime.fromisoformat(tick)).total_seconds()) if tick else None
    except ValueError:
        pass
    ago30 = _iso(now - timedelta(days=30))
    gaps = [{"start": r[0], "end": r[1], "minutes": r[2], "missed": json.loads(r[3] or "{}")}
            for r in _q("SELECT start_at, end_at, minutes, missed FROM service_gaps WHERE end_at >= ? ORDER BY start_at DESC LIMIT 12", (ago30,))]
    since = _q("SELECT MIN(created_at) FROM service_gaps")
    down = sum(g["minutes"] for g in gaps)
    return {"tick": tick, "tick_age_sec": age, "alive": age is not None and age <= scheduler.STALE_AFTER, "gaps": gaps, "down_minutes_30d": down,
            "uptime_pct_30d": round(max(0.0, 100 - down / (30 * 1440) * 100), 1),
            "tracking_since": (since[0][0] if since and since[0][0] else None),
            "note": "꺼져 있던 구간은 이 기능을 켠 뒤부터 기록돼요(그 전 기록은 배치 실행 기록으로만 알 수 있어요)."}


def datasets_section(now: datetime) -> list[dict]:
    try:
        from pipeline import re_store
        st = re_store.states()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for k, v in sorted(st.items()):
        status = str(v.get("status") or "")
        kind = OK if status == "ok" else "setup" if status in ("off", "not_registered", "no_key", "pending", "") else BAD
        ok_at = v.get("last_ok_at")
        stale = False
        try:
            stale = bool(ok_at) and kind == OK and (now - datetime.fromisoformat(str(ok_at)[:19])).total_seconds() > STALE_HOURS * 3600
        except ValueError:
            pass
        out.append({"key": k, "status": status, "level": kind, "stale": stale, "message": str(v.get("message") or "")[:160],
                    "last_ok_at": ok_at, "last_error_at": v.get("last_error_at"), "last_error": str(v.get("last_error") or "")[:140]})
    return out


def apply_section(now: datetime) -> dict:
    start = (now - timedelta(days=20)).date().isoformat()
    rows = {r[0]: (r[1], r[2] or 0) for r in _q("SELECT substr(notice_date,1,10) d, COUNT(*), SUM(source='lh') FROM re_apply_notice WHERE notice_date>=? GROUP BY d", (start,))}
    days = []
    for i in range(20, -1, -1):
        d = (now - timedelta(days=i)).date()
        n, lh = rows.get(d.isoformat(), (0, 0))
        days.append({"date": d.isoformat(), "weekday": d.weekday(), "count": int(n), "lh": int(lh)})
    wk = [x for x in days[-5:] if x["weekday"] < 5]  # 최근 5일 중 평일
    zero_run = len(wk) >= 3 and all(x["count"] == 0 for x in wk)
    last = _q("SELECT MAX(fetched_at), COUNT(*), SUM(source='lh') FROM re_apply_notice")
    return {"days": days, "zero_weekdays": zero_run, "last_fetched": last[0][0] if last else None, "total": last[0][1] if last else 0, "lh_total": (last[0][2] or 0) if last else 0}


def news_section(now: datetime) -> dict:
    d7, d14 = _iso(now - timedelta(days=7)), _iso(now - timedelta(days=14))
    rows = _q("SELECT source, SUM(collected_at>=?), SUM(collected_at<?) FROM articles WHERE collected_at>=? GROUP BY source", (d7, d7, d14))
    total7 = sum(int(r[1] or 0) for r in rows)
    dried = sorted(({"source": r[0], "before": int(r[2] or 0)} for r in rows if not (r[1] or 0) and (r[2] or 0) >= 3), key=lambda x: -x["before"])
    return {"sources_active": sum(1 for r in rows if r[1]), "articles_7d": total7, "dried": dried[:30], "dried_count": len(dried)}


def summarize(svc: dict, jobs: list[dict], datasets: list[dict], apply: dict, news: dict) -> dict:
    reasons: list[dict] = []
    add = lambda lv, t: reasons.append({"level": lv, "text": t})  # noqa: E731
    if not svc["alive"]:
        add(BAD, "예약 작업을 돌리는 스케줄러가 멈춘 것 같아요" + (f" (마지막 확인 {svc['tick_age_sec'] // 60}분 전)." if svc["tick_age_sec"] is not None else "."))
    recent = [g for g in svc["gaps"] if g["end"] >= _iso(datetime.now() - timedelta(hours=24))]
    if recent:
        add(WARN, f"최근 24시간 안에 서버가 {sum(g['minutes'] for g in recent) // 60}시간 이상 꺼져 있던 구간이 있어요.")
    for j in jobs:
        if not j["enabled"] or j["weekly"]:
            continue
        if j["last_ok"]:
            try:
                age_h = (datetime.now() - datetime.fromisoformat(j["last_ok"])).total_seconds() / 3600
            except ValueError:
                age_h = 0
            if age_h > STALE_HOURS and j["kind"] in ("re_data", "reminders"):
                add(BAD, f"'{j['label']}'이 {int(age_h)}시간째 성공하지 못했어요.")
        elif j["kind"] in ("re_data", "reminders"):
            add(WARN, f"'{j['label']}'은 성공한 기록이 아직 없어요.")
        if j["last_failed"]:
            add(WARN, f"'{j['label']}'의 마지막 실행이 실패했어요: {j['last_message'] or '내용 없음'}")
        if j["missed_days"] >= 2 and j["kind"] in ("re_data", "reminders"):
            add(WARN, f"'{j['label']}'이 최근 14일 중 {j['missed_days']}일은 돌지 않았어요.")
    for d in datasets:
        if d["level"] == BAD:
            add(BAD, f"부동산 데이터 '{d['key']}' 오류: {d['last_error'] or d['message']}")
        elif d["stale"]:
            add(WARN, f"부동산 데이터 '{d['key']}'이 {STALE_HOURS}시간 넘게 갱신되지 않았어요.")
    setup = [d["key"] for d in datasets if d["level"] == "setup"]
    if setup:
        add(WARN, f"설정이 필요한 부동산 데이터 {len(setup)}개: {', '.join(setup[:6])} (활용신청·켜기).")
    if apply["zero_weekdays"]:
        add(WARN, "최근 평일 3일 이상 청약 공고가 한 건도 없어요 — 수집이 막혔는지 확인하세요.")
    if news["dried_count"] >= 5:
        add(WARN, f"지난 7일간 기사가 한 건도 없는 뉴스 소스가 {news['dried_count']}곳이에요.")
    level = BAD if any(r["level"] == BAD for r in reasons) else WARN if reasons else OK
    return {"level": level, "reasons": reasons}


@router.get("/health")
def health() -> dict:
    now = datetime.now()
    cfg = settings_store.load()
    svc, jobs, ds, ap, nw = service_section(now), jobs_section(cfg, now), datasets_section(now), apply_section(now), news_section(now)
    return {"now": _iso(now), "summary": summarize(svc, jobs, ds, ap, nw), "service": svc, "jobs": jobs, "datasets": ds, "apply": ap, "news": nw}
