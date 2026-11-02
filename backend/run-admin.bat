@echo off
chcp 65001 >nul
rem 집보미 관리·배치 서버 (5031) — 예약 작업(수집·백업·알림)과 관리 API 를 프로세스 1개로. start-zipbomi.bat 이 띄운다.
rem 공개 서버(5030)는 /api/admin/* 를 여기로 넘긴다 (ZIPGENIE_ADMIN_UPSTREAM). 이 창을 닫으면 관리 화면과 예약 작업이 멈춘다.
cd /d "%~dp0"
set ZIPGENIE_PORT=5031
set ZIPGENIE_SCHEDULER=1
set ZIPGENIE_WORKERS=1
set ZIPGENIE_ADMIN_UPSTREAM=
:loop
venv\Scripts\python serve.py
echo 관리·배치 서버가 멈췄습니다. 5초 뒤 다시 시작합니다...
timeout /t 5 /nobreak >nul
goto loop
