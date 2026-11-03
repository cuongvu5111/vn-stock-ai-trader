# Ngày tạo: 2026-11-03
# Mục đích: Script phục hồi (Restore) PostgreSQL database trading_db từ file dump.

param(
    [Parameter(Mandatory=$true)]
    [string]$InputFile
)

if (-not (Test-Path $InputFile)) {
    Write-Error "Không tìm thấy file backup: $InputFile"
    exit 1
}

Write-Host "Đang phục hồi cơ sở dữ liệu trading_db từ file $InputFile ..."
Get-Content $InputFile -Raw | docker compose exec -T postgres pg_restore -U trader -d trading_db --clean --if-exists
Write-Host "Hoàn tất phục hồi."
