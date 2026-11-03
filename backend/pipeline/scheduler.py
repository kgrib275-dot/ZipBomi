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
            if timedelta(minutes=2) <= now - at <= timedelta(hours=CATCHUP_HOURS) and (latest is None or at > latest):
                latest = at
        if latest is None:
            continue
        minute_key = latest.strftime("%Y-%m-%d %H:%M")
        if _last_fired.get(kind) == minute_key or _claimed(f"{kind}@{minute_key}"):
            continue
        out.append((kind, minute_key))
    return out


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
