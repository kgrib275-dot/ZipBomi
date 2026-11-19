"""앱 내부 배치 스케줄러 (AI_NEWS scheduler.py와 같은 구조).

Streamlit 프로세스가 떠 있는 동안 30초마다 설정을 읽어, 등록된 시각이 되면 작업을
시작한다. 같은 분에 두 번 돌지 않도록 마지막 실행 분을 data/scheduler_last_fired.json에
남긴다(재시작해도 유지).
"""
from __future__ import annotations

import json
import os
import logging
import threading
import time
from datetime import datetime, timedelta

from . import alerts, db, jobs, settings_store
from .db import ROOT

_POLL_SECONDS = 30
_LAST_FIRED_FILE = ROOT / "data" / "scheduler_last_fired.json"
_lock = threading.Lock()
_started = False
logger = logging.getLogger("zipgenie.scheduler")


def _load_last_fired() -> dict:
    try:
        return json.loads(_LAST_FIRED_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_last_fired = _load_last_fired()


def _claim(key: str, minute_key: str) -> bool:
    """여러 서버 프로세스(개발·공개)가 같은 DB를 쓰면 스케줄러도 여러 개 돈다 — DB에 먼저 기록한 한 곳만 실행한다.
    (2026-10-28 실측: 프로세스 3개가 같은 분에 수집을 3번 돌렸다)"""
    conn = db.connect()
    try:
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schedule_claims (slot TEXT PRIMARY KEY, claimed_at TEXT NOT NULL)")
            conn.execute("DELETE FROM schedule_claims WHERE claimed_at < ?", ((datetime.now() - timedelta(days=7)).isoformat(),))
            cur = conn.execute("INSERT OR IGNORE INTO schedule_claims (slot, claimed_at) VALUES (?, ?)",
                               (f"{key}@{minute_key}", datetime.now().isoformat(timespec="seconds")))
            return cur.rowcount == 1
    finally:
        conn.close()


def _fire_once(key: str, now: datetime) -> bool:
    """이번 분에 아직 실행하지 않았으면 기록하고 True (프로세스 안에서도, 프로세스끼리도 한 번)."""
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    with _lock:
        if _last_fired.get(key) == minute_key or not _claim(key, minute_key):
            return False
        _last_fired[key] = minute_key
        _LAST_FIRED_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LAST_FIRED_FILE.write_text(json.dumps(_last_fired), encoding="utf-8")
        return True


def due_jobs(cfg: dict, now: datetime) -> list[str]:
    """지금 시각에 돌아야 할 작업 종류 목록 (테스트하기 쉽게 분리)."""
    hhmm = now.strftime("%H:%M")
    due = []
    for kind, key in (("collect", "collection"), ("draft", "drafting"), ("vectorize", "vectorize"), ("re_data", "re_data"),
                      ("reminders", "reminders")):
        if cfg.get(key, {}).get("enabled") and hhmm in cfg[key]["times"] and hhmm in cfg[key]["times"]:
            due.append(kind)
    for kind in ("weekly", "newsletter", "teams"):
        c = cfg[kind]
        if c["enabled"] and now.weekday() == int(c["weekday"]) and hhmm == c["time"]:
            due.append(kind)
    return due


def missed_weekly(cfg: dict, now: datetime) -> list[str]:
    """이번 주 예정 시각이 지났는데 이번 주 성공 기록이 없는 주간 작업 (PC가 꺼져 있었거나 앱이 내려가 있던 경우)."""
    out = []
    monday = (now - timedelta(days=now.weekday())).date()
    for kind in ("weekly", "newsletter", "teams"):
        c = cfg[kind]
        if not c["enabled"]:
            continue
        hh, mm = map(int, c["time"].split(":"))
        due_at = datetime.combine(monday + timedelta(days=int(c["weekday"])), datetime.min.time()).replace(hour=hh, minute=mm)
        if due_at + timedelta(minutes=5) <= now and not db.ran_ok_since(kind, due_at - timedelta(minutes=1)):
            out.append(kind)
    return out


DAILY = (("collect", "collection"), ("draft", "drafting"), ("vectorize", "vectorize"), ("re_data", "re_data"), ("reminders", "reminders"))
CATCHUP_HOURS = 3  # 정해진 시각을 이만큼 안에서 놓쳤으면 한 번 따라잡는다 (그보다 오래되면 다음 예정 시각을 기다린다)
# 부동산 데이터 수집·알림 메일은 비용이 없고 같은 날 늦게 돌려도 안전해서(알림은 보낸 기록으로 중복을 막는다) 그날 안에는 언제 켜도 따라잡는다 (2026-11-20).
# 예전엔 06:30 배치를 오후 1:40 에 켜면 3시간이 지났다고 건너뛰어, 그날 수집·알림이 통째로 빠졌다.
LONG_CATCHUP = {"re_data", "reminders"}
GAP_MIN_MINUTES = 15  # 예약 확인(tick)이 이만큼 끊겼다가 다시 시작되면 '서버가 꺼져 있던 때'로 기록한다


def _claimed(slot: str) -> bool:
    conn = db.connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schedule_claims (slot TEXT PRIMARY KEY, claimed_at TEXT NOT NULL)")
        return conn.execute("SELECT 1 FROM schedule_claims WHERE slot=?", (slot,)).fetchone() is not None
    finally:
        conn.close()


def missed_daily(cfg: dict, now: datetime) -> list[tuple[str, str]]:
    """오늘 정해진 시각이 지났는데(최근 CATCHUP_HOURS 안) 실행 기록(schedule_claims)이 없는 매일 작업 — (작업, 놓친 'YYYY-MM-DD HH:MM').
    예전엔 매일 작업이 정확히 그 1분에만 돌아, 그때 서버가 재시작 중이거나 꺼져 있으면 그날은 건너뛰었다 (2026-11-03).
    작업마다 가장 최근에 놓친 시각 하나만 돌려준다."""
    out = []
    for kind, key in DAILY:
        c = cfg.get(key, {})
        if not c.get("enabled"):
            continue
        latest = None
        for hhmm in c.get("times") or []:
            try:
                hh, mm = map(int, str(hhmm).split(":"))
            except ValueError:
                continue
            at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            limit = timedelta(hours=24) if kind in LONG_CATCHUP else timedelta(hours=CATCHUP_HOURS)
            if timedelta(minutes=2) <= now - at <= limit and (latest is None or at > latest):
                latest = at
        if latest is None:
            continue
        minute_key = latest.strftime("%Y-%m-%d %H:%M")
        if _last_fired.get(kind) == minute_key or _claimed(f"{kind}@{minute_key}"):
            continue
        if db.ran_ok_since(kind, latest - timedelta(minutes=1)):
            continue  # 관리 화면에서 직접 돌렸거나 다른 경로로 이미 성공했으면 또 돌리지 않는다
        out.append((kind, minute_key))
    return out


# ───────── 서버가 꺼져 있던 때 (2026-11-20) ─────────
_GAP_SQL = ("CREATE TABLE IF NOT EXISTS service_gaps (start_at TEXT PRIMARY KEY, end_at TEXT NOT NULL, minutes INTEGER NOT NULL, "
            "missed TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)")
WEEKLY = ("weekly", "newsletter", "teams")


def slots_between(cfg: dict, start: datetime, end: datetime) -> dict[str, int]:
    """start 이후 end 까지(end 포함) 정해진 시각이 돌아왔던 횟수 — 작업별. 서버가 꺼져 있는 동안 못 돈 작업을 세는 데 쓴다."""
    out: dict[str, int] = {}
    day = start.date()
    for _ in range(62):  # 두 달 넘게 꺼져 있었어도 계산이 길어지지 않게
        if day > end.date():
            break
        for kind, key in DAILY:
            c = cfg.get(key, {})
            if not c.get("enabled"):
                continue
            for hhmm in c.get("times") or []:
                try:
                    hh, mm = map(int, str(hhmm).split(":"))
                except ValueError:
                    continue
                at = datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm)
                if start < at <= end:
                    out[kind] = out.get(kind, 0) + 1
        for kind in WEEKLY:
            c = cfg.get(kind) or {}
            try:
                if c.get("enabled") and day.weekday() == int(c["weekday"]):
                    hh, mm = map(int, str(c["time"]).split(":"))
                    at = datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm)
                    if start < at <= end:
                        out[kind] = out.get(kind, 0) + 1
            except (KeyError, ValueError):
                continue
        day += timedelta(days=1)
    return out


def detect_gap(prev_tick: str | None, now: datetime, cfg: dict) -> dict | None:
    """직전 tick 시각과 지금 사이가 GAP_MIN_MINUTES 보다 길면 {start, end, minutes, missed}. 처음 켠 것(기록 없음)이면 None."""
    try:
        start = datetime.fromisoformat(prev_tick) if prev_tick else None
    except ValueError:
        start = None
    if start is None or now - start < timedelta(minutes=GAP_MIN_MINUTES):
        return None
    return {"start": start.isoformat(timespec="seconds"), "end": now.isoformat(timespec="seconds"),
            "minutes": int((now - start).total_seconds() // 60), "missed": slots_between(cfg, start, now)}


def record_gap(gap: dict) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute(_GAP_SQL)
            conn.execute("INSERT OR REPLACE INTO service_gaps (start_at, end_at, minutes, missed, created_at) VALUES (?,?,?,?,?)",
                         (gap["start"], gap["end"], gap["minutes"], json.dumps(gap["missed"], ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
            conn.execute("DELETE FROM service_gaps WHERE start_at < ?", ((datetime.now() - timedelta(days=400)).isoformat(),))
    finally:
        conn.close()


def _fmt_span(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    d, h = divmod(h, 24)
    return (f"{d}일 " if d else "") + (f"{h}시간 " if h else "") + (f"{m}분" if m and not d else "") or "잠깐"


def _startup_gap_check() -> None:
    """스케줄러가 시작될 때(첫 tick 전) 직전 tick 과 지금의 간격을 보고, 꺼져 있었다면 기록하고 관리자에게 알린다.
    감시 스레드는 같은 PC 에서 돌기 때문에 PC 전체가 꺼졌을 땐 아무도 알릴 수 없었다 — 켜진 직후에야 알 수 있다."""
    now = datetime.now()
    try:
        cfg = settings_store.load()
        gap = detect_gap(db.get_meta("scheduler_tick"), now, cfg)
    except Exception:
        logger.exception("꺼져 있던 시간 확인 오류")
        return
    if not gap:
        return
    record_gap(gap)
    names = {k: v for k, v in alerts.LABELS.items()}
    missed = " · ".join(f"{names.get(k, k)} {n}회" for k, n in gap["missed"].items()) or "예정된 배치 없음"
    logger.warning("서버가 꺼져 있었음: %s ~ %s (%s) · 못 돈 작업: %s", gap["start"], gap["end"], _fmt_span(gap["minutes"]), missed)
    alerts.notify(f"서버가 꺼져 있었어요 ({_fmt_span(gap['minutes'])})",
                  f"{gap['start'].replace('T', ' ')} ~ {gap['end'].replace('T', ' ')} 동안 집보미가 꺼져 있었어요. 그동안 못 돈 작업: {missed}. "
                  "켜진 뒤 부동산 데이터 수집·알림 메일은 오늘 안에 자동으로 따라잡습니다. 지나간 날의 알림은 되돌릴 수 없어요.",
                  key=f"gap:{gap['start']}", path="/admin/health", label="수집 건강 보기")


def _tick() -> None:
    now = datetime.now()
    try:
        cfg = settings_store.load()
    except Exception:
        logger.exception("설정 읽기 실패")
        return
    db.set_meta("scheduler_tick", now.isoformat(timespec="seconds"))
    for kind in due_jobs(cfg, now):
        if _fire_once(kind, now):
            logger.info("스케줄 실행: %s", kind)
            jobs.start(kind, trigger="자동")
    # 놓친 매일 작업 — 원래 시각의 실행 기록(slot)을 차지해 두 번 돌지 않게 한다
    for kind, minute_key in missed_daily(cfg, now):
        if _claim(kind, minute_key):
            with _lock:
                _last_fired[kind] = minute_key
            logger.warning("놓친 매일 작업 따라잡기: %s (%s)", kind, minute_key)
            jobs.start(kind, trigger="자동(놓친 작업)")
    # 놓친 주간 작업은 하루 한 번만 다시 시도한다 (실패가 반복될 때 계속 돌지 않게)
    for kind in missed_weekly(cfg, now):
        if _claim(f"catchup-{kind}", now.strftime("%Y-%m-%d")):
            logger.warning("놓친 주간 작업 따라잡기: %s", kind)
            jobs.start(kind, trigger="자동(놓친 작업)")


def _archive_housekeeping() -> None:
    """지난 날짜 기사 아카이브 확정 (AI_NEWS와 같은 상시 작업 — 시각 등록 없이 매 tick)."""
    from . import archiving
    try:
        done = archiving.archive_pending()
        if done:
            logger.info("데일리 아카이브 확정: %s", ", ".join(done))
    except Exception:
        logger.exception("아카이브 확정 오류")


def _purge_housekeeping() -> None:
    """하루 한 번(프로세스·재시작과 무관하게 DB에 기록): 보관 기간이 지난 기록 삭제 → 통계 갱신 → 백업.
    3.4GB 백업·무결성 검사는 몇 분 걸리므로 별도 스레드에서 한다 (2026-11-03) — 예전엔 그동안 예약 확인(tick)이 멈췄다."""
    global _purged_on
    today = datetime.now().date()
    if _purged_on == today:
        return
    _purged_on = today
    if not _claim("housekeeping", today.isoformat()):
        return  # 오늘 다른 프로세스(또는 재시작 전의 이 프로세스)가 이미 했다
    threading.Thread(target=_housekeeping_run, daemon=True, name="zipbomi-housekeeping").start()


def _housekeeping_run() -> None:
    try:
        for name, n in db.purge_expired().items():
            if n:
                logger.info("보관 기간 지난 %s %d건 삭제", name, n)
    except Exception:
        logger.exception("보관 기간 정리 오류")
    try:
        db.optimize()
    except Exception:
        logger.exception("DB 통계 갱신 오류")
    try:
        p = db.backup(keep=14)
        logger.info("DB 백업: %s", p.name if p else "건너뜀 (오늘 백업 있음 또는 시험용 DB)")
    except Exception:
        logger.exception("DB 백업 오류")
        alerts.notify("DB 백업 실패", "data/logs 로그를 확인하세요.")


_purged_on = None


def _loop() -> None:
    _startup_gap_check()
    while True:
        try:
            _tick()
        except Exception:
            logger.exception("스케줄러 tick 오류")
        _archive_housekeeping()
        _purge_housekeeping()
        time.sleep(_POLL_SECONDS)


WATCH_EVERY = 300      # 5분마다 확인
STALE_AFTER = 600      # 스케줄러 tick 이 10분 넘게 없으면 멈춘 것으로 본다


def _watch_once(now: datetime) -> None:
    tick = db.get_meta("scheduler_tick")
    try:
        age = (now - datetime.fromisoformat(tick)).total_seconds() if tick else None
    except ValueError:
        age = None
    if age is not None and age <= STALE_AFTER:
        return
    since = f"{int(age // 60)}분 전 마지막 실행" if age is not None else "실행 기록 없음"
    # 같은 시(時) 안에서는 한 번만 — 프로세스 3개가 모두 감시해도 DB 기록으로 한 번만 보낸다
    alerts.notify("관리·배치 서버 멈춤",
                  f"예약 작업(백업·수집·알림 메일)을 돌리는 관리·배치 서버(5031)가 멈춘 것 같습니다 ({since}). "
                  "PC 에서 start-zipbomi.bat 을 다시 실행하거나 '집보미 관리·배치 서버 (5031)' 창을 확인하세요.",
                  key=f"admin-down-{now:%H}")


def _watch_loop() -> None:
    time.sleep(WATCH_EVERY)  # 막 함께 시작한 관리·배치 서버가 첫 tick 을 남길 시간을 준다
    while True:
        try:
            _watch_once(datetime.now())
        except Exception:
            logger.exception("관리·배치 서버 감시 오류")
        time.sleep(WATCH_EVERY)


def start_watchdog_thread() -> None:
    """공개 서버(스케줄러 꺼짐, 관리 요청을 5031 로 넘기는 서버)에서만 — 관리·배치 서버가 멈추면 경보를 보낸다 (2026-11-03).
    경보도 원래 5031 이 보내므로, 5031 이 꺼지면 아무도 알 수 없었다."""
    if os.environ.get("ZIPGENIE_SCHEDULER") == "1" or not os.environ.get("ZIPGENIE_ADMIN_UPSTREAM"):
        return
    threading.Thread(target=_watch_loop, daemon=True, name="zipbomi-watchdog").start()


def start_scheduler_thread() -> None:
    """앱 프로세스당 1회만 스레드를 시작한다 (Streamlit 재실행에도 중복 방지).
    ZIPGENIE_SCHEDULER=1인 프로세스(start-public이 설정)만 시작한다 — 개발 서버·시험 서버가 같은 DB로 배치를 또 돌리지 않게.
    ZIPGENIE_NO_SCHEDULER=1이면 어떤 경우에도 시작하지 않는다."""
    global _started
    if os.environ.get("ZIPGENIE_NO_SCHEDULER") == "1" or os.environ.get("ZIPGENIE_SCHEDULER") != "1":
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, daemon=True, name="zipbomi-scheduler").start()
