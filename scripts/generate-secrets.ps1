# Ngày tạo: 2026-11-17
# Mục đích: Sinh secret ngẫu nhiên an toàn (CSPRNG) để dán vào file .env khi chạy Docker Compose/LAN.
# Lý do: không để người vận hành tự nghĩ mật khẩu yếu; script CHỈ in ra màn hình, không ghi file .env và không lưu gì ở đâu cả.
# Dùng được với Windows PowerShell 5.1 và PowerShell 7+ (không cần Python).
#
# Ví dụ:  .\scripts\generate-secrets.ps1

$ErrorActionPreference = 'Stop'

function New-RandomHex {
    param([int]$Bytes)
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return (($buffer | ForEach-Object { $_.ToString('x2') }) -join '')
}

# DB_PASSWORD chỉ gồm hex (an toàn khi ghép vào URL kết nối); JWT_SECRET_KEY 64 hex = 256 bit.
Write-Host '# Dán các dòng sau vào .env (KHÔNG commit .env, KHÔNG chia sẻ):'
Write-Host "DB_PASSWORD=$(New-RandomHex 24)"
Write-Host "JWT_SECRET_KEY=$(New-RandomHex 32)"
Write-Host "BOOTSTRAP_ADMIN_PASSWORD=$(New-RandomHex 12)"
Write-Host '# BOOTSTRAP_ADMIN_PASSWORD là mật khẩu đăng nhập admin lần đầu (24 ký tự hex); đổi lại sau khi đăng nhập nếu muốn.'
