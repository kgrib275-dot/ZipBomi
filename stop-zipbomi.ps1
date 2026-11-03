# 집보미 서버 종료 — 공개 서버(5030)·관리·배치 서버(5031)를 끈다. start-zipbomi.bat 이 시작할 때 부른다.
# 포트를 쥔 python 에서 부모를 거슬러 올라가 그 서버를 돌리는 cmd 창(재시작 반복 :loop)까지 통째로 끈다.
# python 만 끄면 옛 창의 :loop 가 5초 뒤 다시 띄워 포트가 겹친다(Errno 10048).
# Tailscale(zipgenie-tailscaled)은 끄지 않는다 — 새 창이 그대로 다시 쓴다.
param([int[]]$Ports = @(5030, 5031))

# 화면 빌드가 소스보다 오래됐으면 다시 빌드한다 (2026-11-03) — start-zipbomi.bat 은 빌드 결과가 없을 때만 빌드해서,
# 코드를 받은 뒤 'npm run build' 를 잊으면 새 서버에 예전 화면이 그대로 나갔다(휴대폰 로그인 창에 코드 칸이 없던 일).
function Update-FrontendBuild {
    $front = Join-Path $PSScriptRoot 'frontend'
    $index = Join-Path $front 'dist\index.html'
    if (-not (Test-Path (Join-Path $front 'node_modules'))) { return }  # 처음 설치 전이면 bat 의 기존 처리에 맡긴다
    $built = if (Test-Path $index) { (Get-Item $index).LastWriteTime } else { [datetime]::MinValue }
    $newest = Get-ChildItem -Path (Join-Path $front 'src'), (Join-Path $front 'index.html'), (Join-Path $front 'public') -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newest -and $newest.LastWriteTime -gt $built) {
        Write-Host "화면 코드가 바뀌어 다시 빌드합니다 ($($newest.Name))..."
        Push-Location $front
        try { & npm.cmd run build | Out-Host } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { Write-Host '화면 빌드에 실패했습니다. 예전 화면으로 계속합니다 — frontend 에서 npm run build 오류를 확인하세요.' }
    }
}

$procs = @{}
Get-CimInstance Win32_Process | ForEach-Object { $procs[[int]$_.ProcessId] = $_ }

function Get-ServerRoot([int]$procId) {
    # 가장 가까운 cmd.exe 조상(서버 창)을, 없으면 가장 위의 python 조상을 돌려준다.
    $cur = $procs[$procId]; $top = $cur; $seen = @{}
    while ($cur -and -not $seen.ContainsKey([int]$cur.ProcessId)) {
        $seen[[int]$cur.ProcessId] = $true
        if ($cur.Name -ieq 'cmd.exe') { return $cur }
        if ($cur.Name -ieq 'python.exe' -or $cur.Name -ieq 'pythonw.exe') { $top = $cur }
        $parent = $procs[[int]$cur.ParentProcessId]
        # 부모가 먼저 죽고 PID 가 재사용된 경우 — 자식보다 늦게 생긴 "부모"는 따라가지 않는다
        if ($parent -and $parent.CreationDate -gt $cur.CreationDate) { break }
        $cur = $parent
    }
    return $top
}

$targets = @{}
foreach ($port in $Ports) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $listeners) {
        if (-not $procs.ContainsKey([int]$procId)) { continue }
        $root = Get-ServerRoot $procId
        if ($root) { $targets[[int]$root.ProcessId] = "$port 포트 ($($root.Name) PID $($root.ProcessId))" }
    }
}

if ($targets.Count -eq 0) { Write-Host '실행 중인 집보미 서버가 없습니다.'; Update-FrontendBuild; exit 0 }

foreach ($procId in $targets.Keys) {
    Write-Host "기존 서버를 종료합니다: $($targets[$procId])"
    & taskkill.exe /PID $procId /T /F *> $null
}

# 포트가 풀릴 때까지 최대 15초 기다린다
for ($i = 0; $i -lt 30; $i++) {
    $busy = Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue
    if (-not $busy) { Write-Host '기존 서버를 모두 종료했습니다.'; Update-FrontendBuild; exit 0 }
    Start-Sleep -Milliseconds 500
}
Write-Host "포트가 아직 사용 중입니다: $(($busy.LocalPort | Sort-Object -Unique) -join ', ')"
exit 1
