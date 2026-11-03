@echo off
chcp 65001 >nul
rem 집보미 실행 — 127.0.0.1:5030 (AX Review 5012·Trade_IQ 8010 과 별개). 배치 스케줄러 켜짐. 창을 닫으면 서버도 꺼진다.
rem 공개 주소는 별도 Tailscale 기기(zipgenie)의 Funnel 443 — 다른 프로젝트의 공개 포트(443·8443·10000)는 건드리지 않는다.
cd /d "%~dp0"
if not exist frontend\dist\index.html (
  echo 화면을 처음 빌드합니다...
  pushd frontend
  call npm run build
  popd
)
cd backend
rem 2026-11-02 동시 접속 대비: 공개 서버(5030)는 프로세스 3개, 예약 작업·관리는 관리·배치 서버(5031, run-admin.bat) 하나에서.
set ZIPGENIE_PORT=5030
set ZIPGENIE_SCHEDULER=0
set ZIPGENIE_WORKERS=3
set ZIPGENIE_ADMIN_UPSTREAM=http://127.0.0.1:5031
rem 이미 떠 있는 집보미 서버(5030·5031)와 그 창을 끄고 새로 띄운다 — 재시작 반복(Errno 10048) 방지
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-zipbomi.ps1"
if errorlevel 1 (
  echo 기존 서버를 끄지 못했습니다. 실행 중인 창을 직접 닫고 다시 실행하세요.
  timeout /t 10 >nul
  exit /b 1
)
rem 공개 주소 — AX Review·Trade_IQ 의 Funnel(443·8443·10000)과 겹치지 않게 별도 Tailscale 기기 "zipgenie" 를 쓴다.
rem 상태·로그는 backend\data\tailscale (git 제외). 처음 한 번은 tailscale up 로그인 승인이 필요 (README 16장).
set "TS_DIR=%~dp0backend\data\tailscale"
set "TS_EXE=C:\Program Files\Tailscale"
set "TS_SOCK=\\.\pipe\zipgenie-tailscaled"
if exist "%TS_DIR%\tailscaled.state" (
  "%TS_EXE%\tailscale.exe" --socket=%TS_SOCK% status >nul 2>nul
  if errorlevel 1 (
    echo 공개 주소용 Tailscale 기기를 시작합니다...
    start "zipgenie-tailscaled" /min "%TS_EXE%\tailscaled.exe" --windows-mode=dev --tun=userspace-networking --statedir="%TS_DIR%" --socket=%TS_SOCK% --port=41642
  )
)
netstat -ano | findstr /r /c:"127.0.0.1:5031 .*LISTENING" >nul
if errorlevel 1 start "집보미 관리·배치 서버 (5031)" /min "%~dp0backend\run-admin.bat"
echo 집보미 ZIPBOMI: http://localhost:5030  (관리: http://localhost:5030/admin)
if exist "%TS_DIR%\tailscaled.state" echo 공개 주소: https://zipbomi.tail6bd481.ts.net
:loop
venv\Scripts\python serve.py
echo 서버가 멈췄습니다. 5초 뒤 다시 시작합니다... (끝내려면 이 창을 닫으세요)
timeout /t 5 /nobreak >nul
goto loop
