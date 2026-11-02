"""관리 > 부동산 데이터 — 데이터셋별 상태(키 없음/활용신청 필요/정상/꺼짐)·행 수·적용 범위·마지막 실행·켜기/끄기·과거 채우기 개월 수.

실거래가 파일 업로드: POST /admin/redata/upload (multipart file·dataset, 60MB 까지 — pipeline/re_upload.py), GET /admin/redata/uploads (기록).
실행은 관리 > 배치 작업과 같은 jobs.start('re_data', only=[…]) (POST /admin/jobs/re_data). 키 값은 응답에 넣지 않는다.
CSV 자동 다운로드(pipeline/rt_download.py): 데이터셋별 지금 쓰는 출처(API/CSV)·오늘 받은 수/상한·마지막 창·마지막 오류를 함께 준다.
'CSV 자동 다운로드 지금 실행'은 POST /admin/jobs/re_data {csv_only: true}.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from api.deps import require_admin
from api.routers.admin_jobs import log_action
from pipeline import jobs, re_sources, re_store, re_upload, redata, regions_kr, rt_download, rtms, settings_store

router = APIRouter(prefix="/admin/redata", tags=["admin-redata"], dependencies=[Depends(require_admin)])


def _status(d: dict, st: dict | None) -> str:
    if not d["enabled"]:
        return "off"
    if d.get("needs_key") and not rtms.configured():
        return "no_key"
    return (st or {}).get("status") or "pending"


def _view() -> dict:
    re_store.ensure_schema()
    states = re_store.states()
    cov = re_store.coverage()
    counts = re_store.table_counts()
    calls = re_store.calls_today()
    n_regions = len(regions_kr.NAMES)
    uploaded = re_upload.uploaded_totals()
    csv = rt_download.summary()
    out = []
    for d in re_store.datasets():
        st = states.get(d["key"])
        status = _status(d, st)
        c = cov.get(d["key"]) or {}
        is_rtms = d.get("group") == "rtms"
        api = d.get("service") if is_rtms else (f"odcloud:{d['data_id']}" if d.get("group", "").startswith("applyhome") else None)
        out.append({
            "key": d["key"], "name": d["name"], "group": d.get("group"), "desc": d.get("desc", ""),
            "needs_key": bool(d.get("needs_key")), "enabled": d["enabled"], "backfill_months": int(d.get("backfill_months") or 24),
            "status": status, "status_label": re_store.STATUS_LABELS.get(status, status),
            "message": (st or {}).get("message") or "", "last_run_at": (st or {}).get("last_run_at"),
            "last_ok_at": (st or {}).get("last_ok_at"), "last_error": (st or {}).get("last_error"),
            "last_error_at": (st or {}).get("last_error_at"),
            "rows": int(c.get("rows") or 0) if is_rtms else int(counts.get(d["key"], 0)),
            "coverage_from": c.get("ymd_from"), "coverage_to": c.get("ymd_to"),
            "parts": int(c.get("parts") or 0) if is_rtms else None,
            "parts_target": n_regions * int(d.get("backfill_months") or 24) if is_rtms else None,
            "regions": int(c.get("regions") or 0) if is_rtms else None,
            "calls_today": calls.get(api, 0) if api else None, "daily_cap": d["daily_cap"] if d.get("needs_key") else None,
            "backfill_calls": redata.backfill_calls(d) if is_rtms else None,
            "endpoint": (rtms.url(d["service"]) if is_rtms else d.get("endpoint")
                         or ", ".join(e.get("op", "") for e in d.get("endpoints") or [])),
            "data_url": d.get("data_url"),
            "uploadable": is_rtms, "uploaded_rows": uploaded.get(d["key"], 0) if is_rtms else None,
            "source": redata.active_source(d, status) if is_rtms else None,
            "source_setting": redata.source_of(d) if is_rtms else None,
            "csv": _csv_row(csv["datasets"].get(d["key"])) if is_rtms else None,
        })
    _, ecos_sample = re_sources.ecos_key()
    return {
        "key_configured": rtms.configured(), "ecos_key": not ecos_sample, "regions": n_regions,
        "running": "re_data" in jobs.active(), "schedule": settings_store.load().get("re_data"),
        "defaults": re_store.defaults(), "datasets": out, "rejected": re_store.load_config().get("rejected") or [],
        "csv": {k: v for k, v in csv.items() if k != "datasets"},
    }


def _csv_row(c: dict | None) -> dict | None:
    if not c:
        return None
    last, err = c.get("last") or {}, c.get("last_error") or {}
    return {"months": c.get("months", 0), "downloads": c.get("downloads", 0), "inserted": c.get("inserted", 0),
            "last_window": f"{last.get('scope_name')} {last.get('date_from')}~{last.get('date_to')}" if last else None,
            "last_at": last.get("at"), "last_status": last.get("status"), "last_message": last.get("message"),
            # 지난 오류는 그 뒤에 정상으로 받았으면 감춘다
            "last_error": err.get("message") if err and err.get("id", 0) >= last.get("id", 0) else None,
            "last_error_at": err.get("at") if err and err.get("id", 0) >= last.get("id", 0) else None}


@router.get("")
def get_redata() -> dict:
    return _view()


@router.put("/{key}")
def put_dataset(key: str, request: Request, body: dict[str, Any]) -> dict:
    d = re_store.dataset(key)
    if not d:
        raise HTTPException(404, "없는 데이터셋입니다")
    enabled = body.get("enabled")
    months = body.get("backfill_months")
    if enabled is not None and not isinstance(enabled, bool):
        raise HTTPException(400, "enabled 는 true/false 입니다")
    if months is not None:
        try:
            months = int(months)
        except (TypeError, ValueError):
            raise HTTPException(400, "개월 수는 정수입니다")
        if not 1 <= months <= 120:
            raise HTTPException(400, "과거 채우기는 1~120개월입니다")
    re_store.set_conf(key, enabled, months)
    log_action(request, "부동산 데이터 설정", f"{d['name']}: " + ", ".join(
        x for x in (None if enabled is None else ("켜짐" if enabled else "꺼짐"),
                    None if months is None else f"과거 {months}개월") if x))
    return _view()


# ───────────── 실거래가 파일 업로드 (rt.molit.go.kr 에서 받은 CSV·XLSX) ─────────────

@router.post("/upload")
def upload(request: Request, file: UploadFile = File(...), dataset: str = Form("")) -> dict:
    """본문 크기는 main.py 미들웨어가 Content-Length 로 먼저 막고(이 경로만 60MB), 여기서 실제 바이트로 한 번 더 센다."""
    name = Path(file.filename or "").name.strip()[:200] or "upload"
    ext = Path(name).suffix.lower()
    if ext not in re_upload.EXTS:
        raise HTTPException(400, "CSV 또는 XLSX 파일만 올릴 수 있습니다 (.xls 는 사이트에서 CSV 로 받아 주세요).")
    dataset = (dataset or "").strip()
    if dataset and dataset not in re_store.rtms_keys():
        raise HTTPException(400, "없는 데이터셋입니다")
    fd, tmp = tempfile.mkstemp(prefix="zg_upload_", suffix=ext)
    os.close(fd)
    try:
        size = re_upload.save_stream(file.file, Path(tmp))
        res = re_upload.ingest(Path(tmp), name, dataset or None, size)
    except re_upload.UploadError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    log_action(request, "실거래가 파일 업로드", f"{res['dataset_name']} {name}: 새로 {res['inserted']:,} · "
                                          f"중복 {res['duplicates']:,} · 지역 불일치 {res['unmatched']:,}")
    return res


@router.get("/uploads")
def uploads() -> dict:
    return {"uploads": re_upload.history(), "max_mb": re_upload.MAX_BYTES // (1024 * 1024)}
