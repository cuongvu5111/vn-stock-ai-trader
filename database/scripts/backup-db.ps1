# Ngày tạo: 2026-11-03
# Cập nhật: 2026-11-17 — dump bên trong container rồi `docker compose cp` ra máy chủ.
# Mục đích: Sao lưu PostgreSQL (định dạng custom, .dump) của stack Docker Compose.
# Lý do: chuyển hướng `docker compose exec ... > file` bằng PowerShell làm hỏng dữ liệu nhị phân (mã hóa/CRLF) nên
#   bản sao lưu cũ có thể không khôi phục được; cách này không đi qua pipeline văn bản của PowerShell.
# Dùng được với Windows PowerShell 5.1 và PowerShell 7+. Không cần Python hay psql trên máy chủ.
#
# Ví dụ:
#   .\database\scripts\backup-db.ps1
#   .\database\scripts\backup-db.ps1 -OutputDir D:\backups\trading -KeepLast 14

param(
    [string]$OutputDir = '',
    [string]$OutputFile = '',
    [ValidateRange(0, 3650)]
    [int]$KeepLast = 0
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

$running = & docker compose -f $composeFile ps --status running --services
if ($LASTEXITCODE -ne 0 -or -not ($running -contains 'postgres')) {
    throw 'Service postgres chưa chạy. Hãy chạy `docker compose up -d` trước khi sao lưu.'
}

if (-not $OutputDir) { $OutputDir = Join-Path $repoRoot 'backups' }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
if (-not $OutputFile) { $OutputFile = Join-Path $OutputDir "trading_db_$stamp.dump" }
$remotePath = "/tmp/backup_$stamp.dump"

Write-Host "Đang sao lưu PostgreSQL ra $OutputFile ..."
try {
    # POSTGRES_USER/POSTGRES_DB lấy từ môi trường của container nên không cần đọc .env ở máy chủ.
    Invoke-Compose @('exec', '-T', 'postgres', 'sh', '-c', "pg_dump -U `$POSTGRES_USER -d `$POSTGRES_DB -Fc -f $remotePath && pg_restore --list $remotePath > /dev/null")
    Invoke-Compose @('cp', "postgres:$remotePath", $OutputFile)
} finally {
    & docker compose -f $composeFile exec -T postgres rm -f $remotePath 2>$null | Out-Null
}

if (-not (Test-Path $OutputFile) -or (Get-Item $OutputFile).Length -le 0) {
    throw "File sao lưu rỗng hoặc không tồn tại: $OutputFile"
}

if ($KeepLast -gt 0) {
    $dir = Split-Path -Parent (Resolve-Path $OutputFile)
    Get-ChildItem -Path $dir -Filter 'trading_db_*.dump' -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $KeepLast |
        ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Force
            Write-Host "Đã xóa bản sao lưu cũ: $($_.Name)"
        }
}

$sizeKb = [math]::Round((Get-Item $OutputFile).Length / 1KB, 1)
Write-Host "Hoàn tất sao lưu: $OutputFile ($sizeKb KB). File chứa dữ liệu nhạy cảm (băm mật khẩu, sổ lệnh) - hãy bảo vệ nó."
