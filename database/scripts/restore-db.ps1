# Ngày tạo: 2026-11-03
# Cập nhật: 2026-11-17 — copy file vào container rồi pg_restore (không pipe nhị phân qua PowerShell), khôi phục trong một
#   transaction duy nhất và tạm dừng backend trong lúc khôi phục.
# Mục đích: Khôi phục PostgreSQL của stack Docker Compose từ file .dump tạo bởi backup-db.ps1 / service postgres-backup.
# CẢNH BÁO: thao tác GHI ĐÈ toàn bộ dữ liệu hiện tại (--clean --if-exists). Nên sao lưu bản hiện tại trước.
#
# Ví dụ:
#   .\database\scripts\restore-db.ps1 -InputFile .\backups\trading_db_20261117T093000Z.dump

param(
    [Parameter(Mandatory = $true)]
    [string]$InputFile,
    [switch]$Force,
    [switch]$SkipBackendStop
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$composeFile = Join-Path $repoRoot 'docker-compose.yml'

function Invoke-Compose {
    param([string[]]$ComposeArgs)
    & docker compose -f $composeFile @ComposeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($ComposeArgs -join ' ') thất bại (exit $LASTEXITCODE)."
    }
}

if (-not (Test-Path -LiteralPath $InputFile -PathType Leaf)) {
    throw "Không tìm thấy file backup: $InputFile"
}
$InputFile = (Resolve-Path -LiteralPath $InputFile).Path

$running = & docker compose -f $composeFile ps --status running --services
if ($LASTEXITCODE -ne 0 -or -not ($running -contains 'postgres')) {
    throw 'Service postgres chưa chạy. Hãy chạy `docker compose up -d postgres` trước khi khôi phục.'
}

if (-not $Force) {
    Write-Warning "Thao tác này GHI ĐÈ toàn bộ dữ liệu hiện tại bằng nội dung của $InputFile."
    $answer = Read-Host "Gõ RESTORE để xác nhận"
    if ($answer -cne 'RESTORE') { throw 'Đã hủy khôi phục.' }
}

$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$remotePath = "/tmp/restore_$stamp.dump"
$backendWasRunning = $running -contains 'trading-backend'

try {
    # Dừng backend để không còn kết nối/khóa tranh chấp và scheduler không chạy giữa chừng khi dữ liệu đang bị thay thế.
    if ($backendWasRunning -and -not $SkipBackendStop) {
        Write-Host 'Đang dừng trading-backend ...'
        Invoke-Compose @('stop', 'trading-backend')
    }

    Write-Host "Đang khôi phục cơ sở dữ liệu từ $InputFile ..."
    Invoke-Compose @('cp', $InputFile, "postgres:$remotePath")
    Invoke-Compose @('exec', '-T', 'postgres', 'sh', '-c', "pg_restore --list $remotePath > /dev/null")
    # --single-transaction + --exit-on-error: lỗi giữa chừng thì toàn bộ khôi phục bị hủy, dữ liệu hiện tại giữ nguyên.
    Invoke-Compose @('exec', '-T', 'postgres', 'sh', '-c', "pg_restore -U `$POSTGRES_USER -d `$POSTGRES_DB --clean --if-exists --single-transaction --exit-on-error $remotePath")
} finally {
    & docker compose -f $composeFile exec -T postgres rm -f $remotePath 2>$null | Out-Null
    if ($backendWasRunning -and -not $SkipBackendStop) {
        Write-Host 'Đang khởi động lại trading-backend ...'
        & docker compose -f $composeFile start trading-backend
    }
}

Write-Host 'Hoàn tất khôi phục. Hãy chạy POST /api/v1/portfolio/reconcile (hoặc nút Reconcile ở Màn hình 7) để xác nhận sổ cái nhất quán.'
