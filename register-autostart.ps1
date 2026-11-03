# 집보미 자동 시작 등록 (2026-11-03) — Windows 에 로그인하면 start-zipbomi.bat 을 자동으로 실행한다.
# Windows 업데이트로 재부팅된 뒤 운영자가 bat 을 직접 켤 때까지 서비스가 멈추던 문제를 막는다.
#   등록:  powershell -ExecutionPolicy Bypass -File register-autostart.ps1
#   해제:  powershell -ExecutionPolicy Bypass -File register-autostart.ps1 -Remove
# 작업 스케줄러 이름: "ZipBomi 자동 시작". 로그인한 사용자 권한으로 돈다(관리자 권한 필요 없음).
# 참고: 자동 로그인이 꺼져 있으면 재부팅 뒤 로그인해야 시작된다. 절전·최대 절전은 꺼 두는 것이 좋다
#   (powercfg /change standby-timeout-ac 0 ; powercfg /change hibernate-timeout-ac 0).
param([switch]$Remove)
$name = "ZipBomi 자동 시작"
if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "자동 시작을 해제했습니다."
    exit 0
}
$bat = Join-Path $PSScriptRoot "start-zipbomi.bat"
if (-not (Test-Path $bat)) { Write-Host "start-zipbomi.bat 을 찾을 수 없습니다: $bat"; exit 1 }
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c start `"집보미`" /min `"$bat`"" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT1M"  # 로그인 1분 뒤 (네트워크·Tailscale 이 먼저 올라오게)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Description "집보미 공개 서버(5030)·관리·배치 서버(5031) 자동 시작" -Force | Out-Null
Write-Host "등록했습니다: Windows 에 로그인하면 1분 뒤 집보미가 자동으로 시작됩니다. (해제: -Remove)"
