-- Ngày tạo: 2026-11-03
-- Mục đích: Khởi tạo sẵn 6 schemas logic khi container PostgreSQL khởi chạy lần đầu.

CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS analysis;
CREATE SCHEMA IF NOT EXISTS strategy;
CREATE SCHEMA IF NOT EXISTS trading;
CREATE SCHEMA IF NOT EXISTS portfolio;
CREATE SCHEMA IF NOT EXISTS system;
