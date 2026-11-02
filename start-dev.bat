@echo off
chcp 65001 >nul
rem 개발 실행 — 백엔드(5030, 코드 바뀌면 자동 재시작) + 프론트 개발 서버(5183, /api 는 5030 로 프록시)
cd /d "%~dp0"
start "ZipGenie API (5030)" cmd /k "cd backend && set ZIPGENIE_PORT=5030&& venv\Scripts\python serve.py --reload"
start "ZipGenie Front (5183)" cmd /k "cd frontend && npm run dev"
echo 백엔드 http://localhost:5030  ·  화면 http://localhost:5183  (로컬 접속은 관리자)
