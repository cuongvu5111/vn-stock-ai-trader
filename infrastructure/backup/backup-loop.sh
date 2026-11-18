#!/bin/sh
# Ngày tạo: 2026-11-17
# Mục đích: Vòng lặp sao lưu PostgreSQL định kỳ cho service `postgres-backup` (profile `backup` của docker-compose.yml).
# Lý do: chạy trong container riêng, không dùng initdb/cron của máy chủ nên chạy giống nhau trên Windows/Linux.
#   - pg_dump định dạng custom (-Fc) ghi file tạm rồi kiểm tra bằng pg_restore --list mới đổi tên thành bản hợp lệ;
#     file lỗi/dở dang không bao giờ được tính là bản sao lưu.
#   - Giữ lại BACKUP_RETENTION_DAYS ngày nhưng luôn giữ tối thiểu BACKUP_MIN_KEEP bản mới nhất để sao lưu hỏng kéo dài
#     không làm mất toàn bộ bản cũ.
#   - BACKUP_ONCE=1: sao lưu một lần rồi thoát (dùng cho `docker compose run`).
# Biến môi trường: PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE (libpq), BACKUP_INTERVAL_HOURS, BACKUP_RETENTION_DAYS, BACKUP_MIN_KEEP.

set -eu
umask 077

BACKUP_DIR="${BACKUP_DIR:-/backups}"
INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-24}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
MIN_KEEP="${BACKUP_MIN_KEEP:-3}"
RETRY_SECONDS="${BACKUP_RETRY_SECONDS:-300}"

log() {
  printf '{"time":"%s","service":"postgres-backup","message":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"
}

require_positive_int() {
  case "$2" in
    ''|*[!0-9]*) log "$1 phai la so nguyen duong (hien tai: '$2')"; exit 64 ;;
  esac
  if [ "$2" -lt 1 ]; then
    log "$1 phai >= 1"
    exit 64
  fi
}

require_positive_int BACKUP_INTERVAL_HOURS "$INTERVAL_HOURS"
require_positive_int BACKUP_RETENTION_DAYS "$RETENTION_DAYS"
require_positive_int BACKUP_MIN_KEEP "$MIN_KEEP"
require_positive_int BACKUP_RETRY_SECONDS "$RETRY_SECONDS"

backup_once() {
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  partial="$BACKUP_DIR/.${PGDATABASE}_${stamp}.dump.partial"
  final="$BACKUP_DIR/${PGDATABASE}_${stamp}.dump"

  if pg_dump --format=custom --file="$partial" && pg_restore --list "$partial" >/dev/null; then
    mv "$partial" "$final"
    log "backup thanh cong: $(basename "$final")"
  else
    rm -f "$partial"
    log "backup THAT BAI cho database ${PGDATABASE}; se thu lai o chu ky sau"
    return 1
  fi
}

prune_old_backups() {
  # Bỏ qua MIN_KEEP bản mới nhất, trong phần còn lại chỉ xóa bản quá hạn.
  ls -1t "$BACKUP_DIR"/"${PGDATABASE}"_*.dump 2>/dev/null | tail -n +"$((MIN_KEEP + 1))" | while IFS= read -r old_file; do
    if [ -n "$(find "$old_file" -mtime +"$RETENTION_DAYS" 2>/dev/null)" ]; then
      rm -f -- "$old_file"
      log "da xoa ban sao luu qua han: $(basename "$old_file")"
    fi
  done
}

if [ "${BACKUP_ONCE:-0}" = "1" ]; then
  backup_once
  prune_old_backups
  exit 0
fi

trap 'log "nhan tin hieu dung, thoat"; exit 0' TERM INT

log "bat dau: moi ${INTERVAL_HOURS} gio, giu ${RETENTION_DAYS} ngay (toi thieu ${MIN_KEEP} ban), thu muc ${BACKUP_DIR}"
while true; do
  if backup_once; then
    wait_seconds="$((INTERVAL_HOURS * 3600))"
  else
    # Lỗi (ví dụ DB chưa sẵn sàng) thì thử lại sớm thay vì đợi nguyên một chu kỳ.
    wait_seconds="$RETRY_SECONDS"
    [ "$wait_seconds" -gt "$((INTERVAL_HOURS * 3600))" ] && wait_seconds="$((INTERVAL_HOURS * 3600))"
  fi
  prune_old_backups
  # Chạy sleep nền rồi wait để trap xử lý được tín hiệu dừng ngay lập tức.
  sleep "$wait_seconds" &
  wait $!
done
