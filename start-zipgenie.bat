@echo off
chcp 65001 >nul
rem ZipGenie 실행 — 127.0.0.1:5030 (AX Review 5012·Trade_IQ 8010 과 별개). 배치 스케줄러 켜짐. 창을 닫으면 서버도 꺼진다.
rem 공개 주소(Funnel)는 쓰지 않는다 — 다른 프로젝트의 공개 포트(443·8443·10000)를 건드리지 않게.
cd /d "%~dp0"
if not exist frontend\dist\index.html (
  echo 화면을 처음 빌드합니다...
  pushd frontend
  call npm run build
  popd
)
cd backend
set ZIPGENIE_PORT=5030
set ZIPGENIE_SCHEDULER=1
echo ZipGenie: http://localhost:5030  (관리: http://localhost:5030/admin)
:loop
venv\Scripts\python serve.py
echo 서버가 멈췄습니다. 5초 뒤 다시 시작합니다... (끝내려면 이 창을 닫으세요)
timeout /t 5 /nobreak >nul
goto loop
