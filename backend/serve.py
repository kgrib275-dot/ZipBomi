"""서버 실행기.  python serve.py  [--reload]

환경 변수: ZIPGENIE_PORT(기본 5030) · ZIPGENIE_HOST(기본 127.0.0.1) · ZIPGENIE_SCHEDULER=1(배치 실행, start-public 이 설정)
"""
import os
import sys

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("ZIPGENIE_PORT", "5030"))
    host = os.environ.get("ZIPGENIE_HOST", "127.0.0.1")
    # ZIPGENIE_WORKERS: 작업 프로세스 수 (기본 1). 2026-11-02 1만 명 시험: 1개는 초당 약 100건에서 막힌다.
    # 늘리면 처리량은 커지지만 관리 화면의 '실행 중 작업·작업 로그'는 프로세스마다 따로라 다른 프로세스 것이 안 보일 수 있다.
    # 예약 작업은 DB 선점(schedule_claims)으로 한 번만 돈다.
    workers = max(1, min(8, int(os.environ.get("ZIPGENIE_WORKERS", "1") or 1)))
    uvicorn.run("api.main:app", host=host, port=port, reload="--reload" in sys.argv, workers=1 if "--reload" in sys.argv else workers,
                proxy_headers=False,
                log_level="info", access_log=False)
