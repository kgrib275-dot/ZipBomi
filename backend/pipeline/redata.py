"""배치 '부동산 데이터 수집' (jobs kind re_data) — config/re_datasets.yaml 의 데이터셋을 차례로 받아 로컬 DB 에 저장한다.

순서: ① 키 없이 받는 공개 자료(기준금리·ECOS 지표·LH 공고) → ② 청약홈(키) → ③ 국토교통부 실거래가(키, 시군구 × 달).
- 실거래가: 매 실행 '최근 refresh_months 달'(이번 달 + 지난 2달)을 다시 받고(신고 기한 30일·해제 신고로 늦게 바뀜, 20시간 안에
  받은 칸은 건너뜀), 남은 시간·호출로 과거(backfill_months)를 최근 달부터 채운다. 받은 칸은 re_fetch_log 에 남아 다음 실행이 이어 받는다.
- 데이터셋(API)마다 하루 호출 상한(daily_cap ≤ 9,000, DB 집계)과 실행 시간 상한(max_minutes_per_run)을 지킨다.
- 키가 없으면 키가 필요한 데이터셋은 '키 없음'으로 건너뛰고, 활용신청 안 된 API 는 '활용신청 필요'로 표시한 채 다른 데이터셋을 계속한다.
  .env 에 키를 넣으면 다음 실행부터 저절로 받는다 (rtms.api_key 가 .env 를 다시 읽음).
- 진행은 로그 한 줄씩: '✓ 아파트 매매 서울 강남구 2026-09 213건'.
- ④ 실거래가 CSV (pipeline/rt_download.py): 데이터셋마다 source: auto|api|csv (re_datasets.yaml). auto 는 API 가 정상이면 API,
  키 없음·활용신청 필요·오류면 rt.molit.go.kr 의 CSV 를 받아 넣는다. 매일 전국 × 최근 3달(달마다 1건) + 남은 몫으로 시도 × 1년 창
  과거 채우기, 하루 60건 상한. csv_only=True 는 CSV 경로만, dry_run=True 는 오늘 받을 창만 로그에 적고 받지 않는다.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

from pipeline import db, molit, re_sources, re_store, regions_kr, rt_download, rtms

log = logging.getLogger("zipgenie.redata")


def _ymd_label(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:]}"


class _Budget:
    def __init__(self, minutes: float):
        self.end = time.monotonic() + minutes * 60

    def left(self) -> float:
        return self.end - time.monotonic()

    def over(self) -> bool:
        return self.left() <= 0


def _key_missing(d: dict) -> bool:
    return bool(d.get("needs_key")) and not rtms.configured()


def _mark_no_key(d: dict, res: dict) -> None:
    msg = "DATA_GO_KR_KEY 가 없어 건너뜀 — backend/.env 에 키를 넣으면 다음 실행부터 받습니다."
    re_store.set_state(d["key"], "no_key", msg)
    res[d["key"]] = {"status": "no_key", "rows": 0, "calls": 0, "message": msg}
    log.info("– %s: 키 없음 (건너뜀)", d["name"])


def _mark_not_registered(d: dict, res: dict, e: Exception) -> None:
    link = d.get("data_url") or "https://www.data.go.kr"
    msg = f"활용신청 필요 — {link} 에서 [활용신청] 후 승인되면 다음 실행부터 받습니다."
    re_store.set_state(d["key"], "not_registered", msg, error=str(e))
    res[d["key"]] = {"status": "not_registered", "rows": 0, "calls": 0, "message": msg}
    log.warning("✗ %s: 활용신청 필요 (%s)", d["name"], link)


# ───────────────────────── ① 키 없이 받는 자료 ─────────────────────────

def _run_bok(d: dict, c, res: dict) -> None:
    rows = re_sources.bok_base_rate(c)
    at = re_store._now()
    n = re_store.upsert_many("re_base_rate", ("changed_on", "rate", "fetched_at"), [(a, r, at) for a, r in rows])
    re_store.set_state(d["key"], "ok", f"최근 변경 {rows[0][0]} {rows[0][1]:.2f}%", rows=n, ok=True)
    res[d["key"]] = {"status": "ok", "rows": n, "calls": 1}
    log.info("✓ %s %d건 (최근 %s %.2f%%)", d["name"], n, rows[0][0], rows[0][1])


def _run_ecos(d: dict, c, res: dict, delay: float) -> None:
    months = int(d.get("backfill_months") or 60)
    total, calls = 0, 0
    at = re_store._now()
    have = {r["series"]: r["last"] for r in re_store._rows(
        "SELECT series, MAX(period) AS last FROM re_econ_series GROUP BY series")}
    for i, s in enumerate(d.get("series") or []):
        if i:
            time.sleep(delay)
        start, end = re_sources.months_back(months)
        if have.get(s["id"]):  # 이미 받은 계열은 마지막 달 3개월 전부터만 (수정치 반영)
            start = max(start, re_store.shift_ymd(have[s["id"]], -3))
        rows = re_sources.ecos_series(c, s["stat"], s["item"], s.get("cycle", "M"), start, end, delay=delay)
        calls += 1
        vals = []
        for r in rows:
            v = re_store.to_float(r.get("DATA_VALUE"))
            if v is None:
                continue
            vals.append((s["id"], str(r.get("TIME")), v, s.get("name") or r.get("ITEM_NAME1"), s.get("unit") or r.get("UNIT_NAME"), at))
        n = re_store.upsert_many("re_econ_series", ("series", "period", "value", "name", "unit", "fetched_at"), vals)
        total += n
        last = vals[-1] if vals else None
        log.info("✓ %s · %s %d건%s", d["name"], s.get("name") or s["id"], n,
                 f" (최근 {last[1]} {last[2]})" if last else "")
    _, sample = re_sources.ecos_key()
    msg = f"계열 {len(d.get('series') or [])}개" + (" · 공개 sample 키 사용(ECOS_API_KEY 를 넣으면 한 번에 받음)" if sample else "")
    re_store.set_state(d["key"], "ok", msg, rows=total, ok=True)
    res[d["key"]] = {"status": "ok", "rows": total, "calls": calls}


def _run_lh(d: dict, c, res: dict) -> None:
    rows = re_sources.lh_notices(c)
    n = re_store.upsert_notices(rows)
    re_store.set_state(d["key"], "ok", f"공고 목록 {n}건 (임대·분양)", rows=n, ok=True)
    res[d["key"]] = {"status": "ok", "rows": n, "calls": len(re_sources.LH_MENUS)}


# ───────────────────────── ② 청약홈 ─────────────────────────

def _api_name(d: dict) -> str:
    return f"odcloud:{d.get('data_id') or d['key']}"


def _run_apply_notice(d: dict, c, res: dict, delay: float) -> None:
    api, cap = _api_name(d), d["daily_cap"]
    total, calls = 0, 0
    since = (date.today() - timedelta(days=int(d.get("backfill_months") or 24) * 31)).isoformat()
    for ep in d.get("endpoints") or []:
        op = ep["op"]
        if op not in re_sources.APPLY_OPS:
            log.warning("알 수 없는 청약홈 op 건너뜀: %s", op)
            continue
        items = re_sources.odcloud_all(c, op, api, cap, delay=delay)
        calls += max(1, -(-len(items) // 500))
        rows = [r for r in (re_sources.notice_from_applyhome(op, it) for it in items) if r]
        rows = [r for r in rows if not r["notice_date"] or r["notice_date"] >= since]
        n = re_store.upsert_notices(rows)
        total += n
        log.info("✓ 청약 분양공고 %s %d건 (받은 %d건 중 최근 %s 이후)", ep.get("label", op), n, len(items), since)
        time.sleep(delay)
    re_store.set_state(d["key"], "ok", f"공고 {total}건 저장", rows=total, ok=True)
    res[d["key"]] = {"status": "ok", "rows": total, "calls": calls}


def _run_apply_sub(d: dict, c, res: dict, delay: float, budget: _Budget, per_run: int = 400) -> None:
    """공고별 주택형(apply_model) 또는 경쟁률·당첨가점(apply_cmpet) — 아직 없는 공고만, 한 번에 per_run 건까지."""
    api, cap = _api_name(d), d["daily_cap"]
    today = date.today().isoformat()
    since = (date.today() - timedelta(days=int(d.get("backfill_months") or 24) * 31)).isoformat()
    is_model = d["key"] == "apply_model"
    if is_model:
        todo = re_store._rows(
            "SELECT notice_id, op, house_manage_no, pblanc_no, name FROM re_apply_notice n WHERE source='applyhome' "
            "AND notice_date >= ? AND NOT EXISTS (SELECT 1 FROM re_apply_model m WHERE m.notice_id = n.notice_id) "
            "ORDER BY notice_date DESC LIMIT ?", (since, per_run))
    else:
        # 접수가 끝난 공고 — 아직 경쟁률이 없거나, 마감 뒤 열흘 안이면 다시 (늦게 확정되는 2순위 등)
        todo = re_store._rows(
            "SELECT notice_id, op, house_manage_no, pblanc_no, name FROM re_apply_notice n WHERE source='applyhome' "
            "AND receipt_end IS NOT NULL AND receipt_end < ? AND receipt_end >= ? AND (NOT EXISTS "
            "(SELECT 1 FROM re_apply_cmpet m WHERE m.notice_id = n.notice_id) OR receipt_end >= date(?, '-10 day')) "
            "ORDER BY receipt_end DESC LIMIT ?", (today, since, today, per_run))
    total, calls, done = 0, 0, 0
    at = re_store._now()
    for t in todo:
        if budget.over():
            log.info("시간 상한 — %s 나머지는 다음 실행에", d["name"])
            break
        ops = re_sources.APPLY_OPS.get(t["op"])
        if not ops:
            continue
        cond = {"cond[HOUSE_MANAGE_NO::EQ]": t["house_manage_no"]}
        if t["pblanc_no"]:
            cond["cond[PBLANC_NO::EQ]"] = t["pblanc_no"]
        if is_model:
            items = re_sources.odcloud_all(c, ops[2], api, cap, cond=cond, per_page=200, max_pages=3, delay=delay)
            n = re_store.upsert_many("re_apply_model", ("notice_id", "model_no", "house_ty", "area", "households",
                                                        "special_households", "top_amount", "raw", "fetched_at"),
                                     re_sources.model_rows(t["notice_id"], items, at))
            calls += 1
        else:
            items = re_sources.odcloud_all(c, ops[3], api, cap, cond=cond, per_page=500, max_pages=3, delay=delay)
            n = re_store.upsert_many("re_apply_cmpet", ("notice_id", "model_no", "house_ty", "rank", "reside", "households",
                                                        "req_cnt", "rate", "raw", "fetched_at"),
                                     re_sources.cmpet_rows(t["notice_id"], items, at))
            calls += 1
            if ops[0] == "APT":
                time.sleep(delay)
                sc = re_sources.odcloud_all(c, re_sources.SCORE_OP, api, cap, cond=cond, per_page=500, max_pages=3,
                                            delay=delay)
                n += re_store.upsert_many("re_apply_score", ("notice_id", "model_no", "house_ty", "reside", "low", "top",
                                                             "avg", "raw", "fetched_at"),
                                          re_sources.score_rows(t["notice_id"], sc, at))
                calls += 1
        total += n
        done += 1
        log.info("✓ %s %s %d건", d["name"], t["name"][:30], n)
        time.sleep(delay)
    re_store.set_state(d["key"], "ok", f"공고 {done}/{len(todo)}건 처리", rows=total, ok=True)
    res[d["key"]] = {"status": "ok", "rows": total, "calls": calls}


# ───────────────────────── ③ 실거래가 ─────────────────────────

def plan_rtms(d: dict, refresh_months: int, now: datetime | None = None) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(다시 받을 칸, 과거 채울 칸) — 칸 = (시군구, YYYYMM). 다시 받을 칸 중 20시간 안에 받은 것은 뺀다."""
    now = now or datetime.now(db.KST)
    cur = re_store.this_ymd()
    recent = [re_store.shift_ymd(cur, -i) for i in range(refresh_months)]
    back = [re_store.shift_ymd(cur, -i) for i in range(refresh_months, max(refresh_months, int(d["backfill_months"])))]
    have = re_store.fetched_parts(d["key"])
    lawds = list(regions_kr.NAMES)
    refresh = []
    for ymd in recent:
        for lawd in lawds:
            at = have.get((lawd, ymd))
            if at:
                try:
                    if now - datetime.fromisoformat(at) < timedelta(hours=20):
                        continue
                except ValueError:
                    pass
            refresh.append((lawd, ymd))
    backfill = [(lawd, ymd) for ymd in back for lawd in lawds if (lawd, ymd) not in have]
    return refresh, backfill


def _run_rtms(d: dict, c, res: dict, delay: float, refresh_months: int, deadline: float, backfill: bool = True) -> None:
    refresh, back = plan_rtms(d, refresh_months)
    todo = refresh + (back if backfill else [])
    total, calls, done, errors, consecutive = 0, 0, 0, 0, 0
    stop_msg = ""
    if not todo:
        msg = "받을 칸 없음 (최근 달은 20시간 안에 받았고 과거 채우기 끝)"
        re_store.set_state(d["key"], "ok", msg, rows=0, ok=True)
        res[d["key"]] = {"status": "ok", "rows": 0, "calls": 0, "message": msg}
        log.info("· %s: %s", d["name"], msg)
        return
    log.info("▷ %s: 최근 %d칸 + 과거 %d칸 대상", d["name"], len(refresh), len(back) if backfill else 0)
    for lawd, ymd in todo:
        if time.monotonic() > deadline:
            stop_msg = "시간 몫을 다 써서 멈춤 — 다음 실행에 이어서"
            break
        try:
            items, n_calls = rtms.fetch_items(d["service"], lawd, ymd, client=c, cap=d["daily_cap"])
        except rtms.NotRegistered as e:
            if done == 0:
                _mark_not_registered(d, res, e)
                return
            raise
        except rtms.LimitExceeded as e:
            stop_msg = str(e)
            break
        except rtms.RtmsError as e:
            errors += 1
            consecutive += 1
            log.warning("✗ %s %s %s: %s", d["name"], regions_kr.NAMES.get(lawd, lawd), _ymd_label(ymd), e)
            if consecutive >= 5:
                stop_msg = f"연속 오류 {consecutive}번 — 멈춤 ({e})"
                break
            time.sleep(3)
            continue
        consecutive = 0
        calls += n_calls
        n = re_store.replace_partition(d["key"], lawd, ymd, items, n_calls)
        if d["key"] == "apt_trade":  # /deals 화면 캐시도 같이 채운다 (화면이 공공 API 를 다시 부르지 않게)
            try:
                molit._store(lawd, ymd, [x for x in (molit.parse_item(it) for it in items) if x])
            except Exception:  # noqa: BLE001 - 캐시 실패는 배치를 막지 않는다
                log.debug("화면 캐시 저장 실패", exc_info=True)
        total += n
        done += 1
        log.info("✓ %s %s %s %d건", d["name"], regions_kr.NAMES.get(lawd, lawd), _ymd_label(ymd), n)
        time.sleep(delay)
    left = len(todo) - done
    status = "limit" if "한도" in stop_msg else ("error" if errors and not done else "ok")
    msg = f"{done}칸 {total:,}건 받음" + (f" · 남은 {left}칸" if left else " · 대상 칸 모두 받음") + (f" · {stop_msg}" if stop_msg else "")
    if errors:
        msg += f" · 오류 {errors}칸"
    re_store.set_state(d["key"], status, msg, rows=total, ok=status != "error",
                       error=stop_msg if status == "error" else None)
    res[d["key"]] = {"status": status, "rows": total, "calls": calls, "parts": done, "left": left, "errors": errors,
                     "message": msg}
    log.info("■ %s: %s", d["name"], msg)


# ───────────────────────── ④ 실거래가 CSV (rt.molit.go.kr) ─────────────────────────

_API_DOWN = ("no_key", "not_registered", "error")


def source_of(d: dict) -> str:
    s = str(d.get("source") or "auto").strip().lower()
    return s if s in ("auto", "api", "csv") else "auto"


def csv_wanted(d: dict, api_status: str | None) -> bool:
    """이 실거래가 데이터셋을 CSV 로 받을지 — csv 는 늘, api 는 안 함, auto 는 API 가 키 없음·활용신청 필요·오류일 때."""
    if d.get("group") != "rtms" or d["key"] not in rt_download.CODES:
        return False
    src = source_of(d)
    if src != "auto":
        return src == "csv"
    return api_status in _API_DOWN or (api_status is None and not rtms.configured())


def active_source(d: dict, api_status: str | None) -> str:
    """관리 화면 표시용 'API' · 'CSV'."""
    return "CSV" if csv_wanted(d, api_status) else "API"


def _run_csv(targets: list[dict], res: dict, deadline: float, dry_run: bool = False) -> dict:
    out = rt_download.run(targets, deadline, dry_run=dry_run)
    for d in targets:
        pd = out["per_dataset"].get(d["key"]) or {}
        r = res.setdefault(d["key"], {"status": "pending", "rows": 0, "calls": 0})
        r["source"] = "csv"
        r["csv"] = pd
        r["rows"] = r.get("rows", 0) + int(pd.get("inserted") or 0)
        if dry_run:
            continue
        if pd or r["status"] == "pending":  # CSV 가 이 데이터셋을 다뤘으면 결과 상태는 CSV 기준
            r["status"] = "error" if pd.get("error") else "ok"
            if pd.get("error"):
                r["message"] = f"CSV: {pd['error']}"[:300]
    return out


def _csv_only(all_ds: list[dict], only: list[str] | None, dry_run: bool, budget: _Budget, res: dict) -> dict:
    states = re_store.states()
    targets = []
    for d in all_ds:
        if d.get("group") != "rtms" or (only and d["key"] not in only) or (not d["enabled"] and not only):
            continue
        st = (states.get(d["key"]) or {}).get("status")
        if (only and source_of(d) != "api" and d["key"] in rt_download.CODES) or csv_wanted(d, st):
            targets.append(d)
            res[d["key"]] = {"status": "pending", "rows": 0, "calls": 0}
    log.info("실거래가 CSV %s — 대상 %d개: %s", "계획만 (시험 실행)" if dry_run else "자동 다운로드", len(targets),
             ", ".join(d["name"] for d in targets) or "없음")
    minutes = float(re_store.defaults().get("csv_max_minutes", 60))
    return _run_csv(targets, res, time.monotonic() + min(minutes * 60, max(budget.left(), 20 * 60)), dry_run=dry_run)


# ───────────────────────── 실행 ─────────────────────────

def run(only: list[str] | None = None, backfill: bool = True, csv_only: bool = False, dry_run: bool = False) -> dict:
    """jobs.run('re_data') 이 부른다. only = 이 데이터셋 키만 (관리 화면 '지금 실행').
    csv_only = 실거래가 CSV 자동 다운로드만 (관리 화면 'CSV 자동 다운로드 지금 실행'), dry_run = CSV 계획만 로그에 적고 받지 않는다."""
    re_store.ensure_schema()
    base = re_store.defaults()
    delay = float(base.get("delay_sec", 0.2))
    refresh_months = max(1, int(base.get("refresh_months", 3)))
    budget = _Budget(float(base.get("max_minutes_per_run", 150)))
    all_ds = re_store.datasets()
    if only:
        unknown = set(only) - {d["key"] for d in all_ds}
        if unknown:
            raise ValueError(f"없는 데이터셋: {', '.join(sorted(unknown))}")
    res: dict[str, dict] = {}
    if csv_only or dry_run:
        return _finish(res, _csv_only(all_ds, only, dry_run, budget, res))
    log.info("부동산 데이터 수집 시작 — API 키 %s, 데이터셋 %d개%s", "있음" if rtms.configured() else "없음", len(all_ds),
             f" (선택: {', '.join(only)})" if only else "")
    targets = []
    rtms_considered = []  # API 로 받든 CSV 로 받든 이번에 다룰 실거래가 데이터셋
    for d in all_ds:
        if only and d["key"] not in only:
            continue
        if not d["enabled"] and not only:
            re_store.set_state(d["key"], "off", "꺼짐 (관리 > 부동산 데이터에서 켜기)")
            res[d["key"]] = {"status": "off", "rows": 0, "calls": 0}
            continue
        if d.get("group") == "rtms":
            rtms_considered.append(d)
            if source_of(d) == "csv":  # API 를 부르지 않고 CSV 로만
                res[d["key"]] = {"status": "pending", "rows": 0, "calls": 0}
                continue
        if _key_missing(d):
            _mark_no_key(d, res)
            continue
        targets.append(d)

    order = {"bok": 0, "ecos": 0, "lh": 0, "applyhome": 1, "applyhome_sub": 2, "rtms": 3}
    targets.sort(key=lambda d: order.get(d.get("group", ""), 9))
    rtms_targets = [d for d in targets if d.get("group") == "rtms"]
    with re_sources.client() as c:
        for d in targets:
            if d.get("group") == "rtms":
                continue
            if budget.over():
                res[d["key"]] = {"status": "pending", "rows": 0, "calls": 0, "message": "시간 상한으로 다음 실행에"}
                continue
            try:
                g = d.get("group")
                if g == "bok":
                    _run_bok(d, c, res)
                elif g == "ecos":
                    _run_ecos(d, c, res, max(delay, 0.4))
                elif g == "lh":
                    _run_lh(d, c, res)
                elif g == "applyhome":
                    _run_apply_notice(d, c, res, max(delay, 0.3))
                elif g == "applyhome_sub":
                    _run_apply_sub(d, c, res, max(delay, 0.3), budget)
                else:
                    log.warning("알 수 없는 그룹 %s — 건너뜀", g)
            except rtms.NotRegistered as e:
                _mark_not_registered(d, res, e)
            except rtms.KeyMissing:
                _mark_no_key(d, res)
            except rtms.LimitExceeded as e:
                re_store.set_state(d["key"], "limit", str(e))
                res[d["key"]] = {"status": "limit", "rows": 0, "calls": 0, "message": str(e)}
                log.warning("✗ %s: %s", d["name"], e)
            except Exception as e:  # noqa: BLE001 - 한 데이터셋 실패가 나머지를 막지 않는다
                msg = f"{type(e).__name__}: {e}"[:300]
                re_store.set_state(d["key"], "error", msg, error=msg)
                res[d["key"]] = {"status": "error", "rows": 0, "calls": 0, "message": msg}
                log.warning("✗ %s 실패: %s", d["name"], msg)
            time.sleep(delay)

        # 실거래가 — 남은 시간을 남은 데이터셋 수로 나눠 앞 데이터셋이 시간을 다 쓰지 않게 (남긴 몫은 뒤로 넘어간다)
        for i, d in enumerate(rtms_targets):
            if budget.over():
                res[d["key"]] = {"status": "pending", "rows": 0, "calls": 0, "message": "시간 상한으로 다음 실행에"}
                continue
            share = budget.left() / (len(rtms_targets) - i)
            try:
                _run_rtms(d, c, res, delay, refresh_months, time.monotonic() + share, backfill=backfill)
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"[:300]
                re_store.set_state(d["key"], "error", msg, error=msg)
                res[d["key"]] = {"status": "error", "rows": 0, "calls": 0, "message": msg}
                log.warning("✗ %s 실패: %s", d["name"], msg)

    # 실거래가 CSV — API 로 못 받은(또는 source: csv) 데이터셋만
    csv = None
    csv_targets = [d for d in rtms_considered if csv_wanted(d, (res.get(d["key"]) or {}).get("status"))]
    if csv_targets:
        minutes = float(base.get("csv_max_minutes", 60))
        try:
            csv = _run_csv(csv_targets, res, time.monotonic() + min(minutes * 60, max(budget.left(), 20 * 60)))
        except Exception as e:  # noqa: BLE001 - CSV 실패가 배치 결과를 지우지 않게
            csv = {"stopped": f"{type(e).__name__}: {e}"[:300], "errors": 1, "downloads": 0}
            log.warning("✗ 실거래가 CSV 실패: %s", csv["stopped"])
    return _finish(res, csv)


def _finish(res: dict, csv: dict | None) -> dict:
    counts: dict[str, int] = {}
    for v in res.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    out = {"key": rtms.configured(), "datasets": res, "counts": counts,
           "rows": sum(v.get("rows", 0) for v in res.values()), "calls": sum(v.get("calls", 0) for v in res.values())}
    if csv is not None:
        out["csv"] = {k: v for k, v in csv.items() if k not in ("per_dataset", "plan")}
        if csv.get("plan") is not None:  # 실행 기록에는 오늘 받을 창만 (전체는 작업 로그에)
            out["csv"]["plan_total"] = len(csv["plan"])
            out["csv"]["plan"] = [f"{w['dataset']} {w['label']}" for w in csv["plan"] if w.get("within_cap")]
    try:  # 기준금리·주담대 금리가 새로 들어왔으면 현행 수치(/now)도 맞춘다
        from pipeline import policy
        ch = policy.refresh_auto()["changed"]
        if ch:
            log.info("현행 수치 자동 항목 갱신: %s", ", ".join(ch))
    except Exception:  # noqa: BLE001 - 수집 결과에는 영향 없음
        log.exception("현행 수치 자동 갱신 실패")
    log.info("부동산 데이터 수집 끝 — %s · 저장 %d건 · 호출 %d번",
             ", ".join(f"{re_store.STATUS_LABELS.get(k, k)} {n}" for k, n in counts.items()), out["rows"], out["calls"])
    return out


def judge(result: dict) -> tuple[bool, list[str]]:
    """활용신청 필요·오류·한도는 '경고', 시도한 데이터셋이 모두 오류일 때만 실패.
    '키 없음'은 키를 넣기 전 정상 상태라 경고로 보내지 않는다 (매일 경보 메일이 가지 않게 — 실행 기록 요약에는 남는다)."""
    c = result.get("counts") or {}
    warn = []
    if c.get("not_registered"):
        warn.append(f"활용신청 필요 {c['not_registered']}개")
    if c.get("error"):
        warn.append(f"오류 {c['error']}개")
    if c.get("limit"):
        warn.append(f"한도 도달 {c['limit']}개")
    csv = result.get("csv") or {}
    if csv.get("errors") and csv.get("stopped"):
        warn.append(f"CSV 자동 다운로드 멈춤 ({str(csv['stopped'])[:80]})")
    tried = sum(n for k, n in c.items() if k in ("ok", "error", "limit"))
    return not (tried and c.get("error", 0) >= tried), warn


def backfill_calls(d: dict) -> int:
    """24개월(또는 설정 개월) 과거 채우기에 필요한 최소 호출 수 (시군구 × 달, 1천 건 넘는 쪽은 더)."""
    if d.get("group") != "rtms":
        return 0
    return len(regions_kr.NAMES) * int(d.get("backfill_months") or 24)
