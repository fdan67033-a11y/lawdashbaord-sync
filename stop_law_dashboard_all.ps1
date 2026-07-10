$ErrorActionPreference = 'SilentlyContinue'
$Port = 6155
$DashboardFolder = 'C:\todo_manual_dashboard\law_dashboard_work\law_dashboard_json_v36_fhd_pdf_preview_cache'

Write-Host '[Law Dashboard Stop] Start'
Write-Host ('Target port: ' + $Port)
Write-Host ('Target folder: ' + $DashboardFolder)

# 1) Stop the process listening on the dashboard port.
$portPids = @()
try {
    $portPids = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
} catch {
    $portPids = @()
}

if (-not $portPids -or $portPids.Count -eq 0) {
    try {
        $netstatLines = netstat -ano | Select-String (':' + $Port + '\s+.*LISTENING')
        foreach ($line in $netstatLines) {
            $parts = ($line.ToString() -split '\s+') | Where-Object { $_ -ne '' }
            if ($parts.Count -ge 5) { $portPids += [int]$parts[-1] }
        }
        $portPids = $portPids | Select-Object -Unique
    } catch {}
}

foreach ($pidValue in $portPids) {
    if ($pidValue -and $pidValue -ne $PID) {
        try {
            Write-Host ('Stopping port listener PID ' + $pidValue)
            Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        } catch {}
    }
}

# 2) Stop only dashboard-related Python processes.
$processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.Name -match '^(python|pythonw|py)\.exe$') -and
    (
        ($_.CommandLine -like '*law_dashboard_work*') -or
        ($_.CommandLine -like '*app_law_*') -or
        ($_.CommandLine -like ('*' + $DashboardFolder + '*'))
    )
}

foreach ($proc in $processes) {
    if ($proc.ProcessId -and $proc.ProcessId -ne $PID) {
        try {
            Write-Host ('Stopping dashboard python PID ' + $proc.ProcessId)
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        } catch {}
    }
}

Start-Sleep -Milliseconds 500
Write-Host '[Law Dashboard Stop] Done'
