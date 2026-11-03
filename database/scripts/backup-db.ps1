# Ngày tạo: 2026-11-03
# Mục đích: Script sao lưu (Backup) PostgreSQL database trading_db.

param(
    [string]$OutputFile = "backup_trading_db_$(Get-Date -Format 'yyyyMMdd_HHmmss').dump"
)

Write-Host "Đang sao lưu cơ sở dữ liệu trading_db ra file $OutputFile ..."
docker compose exec -T postgres pg_dump -U trader -d trading_db -F c > $OutputFile
Write-Host "Hoàn tất sao lưu: $OutputFile"
