# Ngày tạo: 2026-11-03
# Mục đích: Xử lý nghiệp vụ quản lý mã cổ phiếu, import CSV idempotent và truy vấn lịch sử giá OHLCV.
# Lý do: Đảm bảo toàn bộ quy tắc kiểm tra dữ liệu, lưu vết nguồn (source_id, import_batch_id) và không nhân đôi bản ghi.

import uuid
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

import structlog
from fastapi import HTTPException, status
from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.indicators.models import AiReport, StockSignal, TechnicalIndicator
from app.market_data.csv_provider import CsvMarketDataProvider
from app.market_data.models import DailyPrice, DataSource, ImportBatch, Stock
from app.market_data.validators import validate_ohlcv_rows
from app.market_data.vn_live_provider import (
    DEFAULT_REAL_VN_STOCKS,
    VnMarketLiveHttpProvider,
)
from app.schemas.market_data import (
    DailyPriceItemResponse,
    ImportBatchResponse,
    MarketOverviewResponse,
    StockCreateRequest,
    StockHistoryResponse,
    StockListResponse,
    StockResponse,
    StockUpdateRequest,
    SyncRealMarketRequest,
    SyncRealMarketResponse,
)
from app.strategies.models import BacktestTrade
from app.trading.models import Approval, TradeProposal

logger = structlog.get_logger(__name__)


class MarketDataService:
    """Service điều phối toàn bộ nghiệp vụ của phân hệ Market Data."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.csv_provider = CsvMarketDataProvider()

    # ------------------------------------------------------------------
    # Quản lý Cổ phiếu (Stock CRUD)
    # ------------------------------------------------------------------

    def list_stocks(
        self,
        exchange: Optional[str] = None,
        is_active: Optional[bool] = None,
        query_text: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> StockListResponse:
        """Lấy danh sách cổ phiếu có bộ lọc và phân trang."""
        stmt: Select[Tuple[Stock]] = select(Stock)

        if exchange:
            stmt = stmt.where(Stock.exchange == exchange.strip().upper())
        if is_active is not None:
            stmt = stmt.where(Stock.is_active == is_active)
        if query_text:
            pattern = f"%{query_text.strip().upper()}%"
            stmt = stmt.where(Stock.symbol.ilike(pattern))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = int(self.session.scalar(count_stmt) or 0)

        rows = self.session.scalars(
            stmt.order_by(Stock.symbol.asc()).limit(limit).offset(offset)
        ).all()

        return StockListResponse(
            total=total,
            limit=limit,
            offset=offset,
            items=[StockResponse.model_validate(item) for item in rows],
        )

    def create_stock(self, payload: StockCreateRequest) -> StockResponse:
        """Tạo mới một mã cổ phiếu; báo lỗi 409 nếu mã đã tồn tại."""
        existing = self.session.scalar(select(Stock).where(Stock.symbol == payload.symbol))
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Mã cổ phiếu '{payload.symbol}' đã tồn tại trong hệ thống.",
            )

        company_name = payload.company_name
        if payload.is_sample and company_name and not company_name.startswith("[SAMPLE]"):
            company_name = f"[SAMPLE] {company_name}"
        elif payload.is_sample and not company_name:
            company_name = f"[SAMPLE] Cổ phiếu mẫu {payload.symbol}"

        stock = Stock(
            symbol=payload.symbol,
            exchange=payload.exchange,
            company_name=company_name,
            sector=payload.sector,
            is_active=payload.is_active,
        )
        self.session.add(stock)
        self.session.commit()
        self.session.refresh(stock)
        return StockResponse.model_validate(stock)

    def update_stock(self, symbol: str, payload: StockUpdateRequest) -> StockResponse:
        """Cập nhật thông tin một mã cổ phiếu theo symbol."""
        normalized_symbol = symbol.strip().upper()
        stock = self.session.scalar(select(Stock).where(Stock.symbol == normalized_symbol))
        if not stock:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy mã cổ phiếu '{normalized_symbol}'.",
            )

        if payload.exchange is not None:
            stock.exchange = payload.exchange
        if payload.company_name is not None:
            stock.company_name = payload.company_name
        if payload.sector is not None:
            stock.sector = payload.sector
        if payload.is_active is not None:
            stock.is_active = payload.is_active

        self.session.commit()
        self.session.refresh(stock)
        return StockResponse.model_validate(stock)

    # ------------------------------------------------------------------
    # Import CSV Idempotent & Batch Tracking
    # ------------------------------------------------------------------

    def get_or_create_data_source(
        self, source_name: str, provider_type: str = "CSV", license_notes: Optional[str] = None
    ) -> DataSource:
        """Lấy hoặc tạo mới bản ghi nguồn dữ liệu trong market.data_sources."""
        cleaned_name = source_name.strip()
        source = self.session.scalar(select(DataSource).where(DataSource.name == cleaned_name))
        if not source:
            source = DataSource(
                name=cleaned_name,
                provider_type=provider_type,
                license_notes=license_notes
                or "SAMPLE / SIMULATED DATA ONLY — Dữ liệu phục vụ nghiên cứu & Paper Trading.",
            )
            self.session.add(source)
            self.session.flush()
        return source

    def import_csv_content(
        self,
        csv_text: str,
        file_name: str = "upload.csv",
        source_name: str = "CSV_SAMPLE_SOURCE",
        license_notes: Optional[str] = None,
        auto_create_stocks: bool = True,
        is_sample: bool = True,
    ) -> ImportBatchResponse:
        """
        Thực hiện import dữ liệu OHLCV từ chuỗi CSV:
        1. Tính SHA-256 checksum & tạo ImportBatch.
        2. Kiểm tra tính hợp lệ từng dòng (validate_ohlcv_rows).
        3. Upsert idempotent vào market.daily_prices (chạy lại cùng file không nhân đôi bản ghi).
        4. Lưu chi tiết các dòng bị từ chối và cảnh báo thiếu ngày giao dịch.
        """
        started_at = datetime.now(timezone.utc)
        source = self.get_or_create_data_source(
            source_name=source_name, provider_type="CSV", license_notes=license_notes
        )

        raw_rows, checksum = self.csv_provider.load_from_string(csv_text)

        batch = ImportBatch(
            source_id=source.id,
            file_name=file_name,
            checksum=checksum,
            started_at=started_at,
            status="PROCESSING",
            rows_read=len(raw_rows),
            rows_inserted=0,
            rows_rejected=0,
        )
        self.session.add(batch)
        self.session.flush()

        valid_rows, rejected_rows, missing_weekdays = validate_ohlcv_rows(
            raw_rows=raw_rows,
            market_timezone=self.settings.MARKET_TIMEZONE,
        )

        # Bộ nhớ đệm symbol -> Stock entity để tránh query lặp lại
        stock_cache: Dict[str, Stock] = {
            s.symbol: s for s in self.session.scalars(select(Stock)).all()
        }

        rows_inserted = 0
        rows_updated_or_unchanged = 0
        additional_rejections = list(rejected_rows)

        for vrow in valid_rows:
            stock = stock_cache.get(vrow.symbol)
            if not stock:
                if not auto_create_stocks:
                    from app.market_data.validators import RejectedOhlcvRow

                    additional_rejections.append(
                        RejectedOhlcvRow(
                            row_number=vrow.row_number,
                            raw_data={"symbol": vrow.symbol, "trading_date": vrow.trading_date.isoformat()},
                            error_code="UNKNOWN_SYMBOL",
                            error_message=f"Mã cổ phiếu '{vrow.symbol}' chưa tồn tại trong danh mục.",
                        )
                    )
                    continue

                label_prefix = "[SAMPLE] " if (is_sample or vrow.data_label == "SAMPLE") else ""
                stock = Stock(
                    symbol=vrow.symbol,
                    exchange=vrow.exchange,
                    company_name=f"{label_prefix}Cổ phiếu {vrow.symbol}",
                    is_active=True,
                )
                self.session.add(stock)
                self.session.flush()
                stock_cache[vrow.symbol] = stock

            # Kiểm tra bản ghi hiện hữu theo khóa duy nhất (stock_id, trading_date, source_id)
            existing_price = self.session.scalar(
                select(DailyPrice).where(
                    DailyPrice.stock_id == stock.id,
                    DailyPrice.trading_date == vrow.trading_date,
                    DailyPrice.source_id == source.id,
                )
            )

            if existing_price is None:
                new_price = DailyPrice(
                    stock_id=stock.id,
                    source_id=source.id,
                    import_batch_id=batch.id,
                    trading_date=vrow.trading_date,
                    open=vrow.open,
                    high=vrow.high,
                    low=vrow.low,
                    close=vrow.close,
                    adjusted_close=vrow.adjusted_close,
                    volume=vrow.volume,
                )
                self.session.add(new_price)
                rows_inserted += 1
            else:
                # Idempotent update: cập nhật giá trị nếu có điều chỉnh nhưng không tạo dòng trùng
                existing_price.open = vrow.open
                existing_price.high = vrow.high
                existing_price.low = vrow.low
                existing_price.close = vrow.close
                existing_price.adjusted_close = vrow.adjusted_close
                existing_price.volume = vrow.volume
                existing_price.import_batch_id = batch.id
                rows_updated_or_unchanged += 1

        total_rejected = len(additional_rejections)
        if len(raw_rows) == 0 or (rows_inserted == 0 and rows_updated_or_unchanged == 0 and total_rejected > 0):
            final_status = "FAILED"
        elif total_rejected > 0:
            final_status = "COMPLETED_WITH_ERRORS"
        else:
            final_status = "COMPLETED"

        error_detail = {
            "rows_updated_or_idempotent": rows_updated_or_unchanged,
            "rejected_rows": [
                {
                    "row_number": r.row_number,
                    "error_code": r.error_code,
                    "error_message": r.error_message,
                    "raw_data": r.raw_data,
                }
                for r in additional_rejections
            ],
            "warnings": {
                "missing_weekdays": missing_weekdays,
            },
        }

        batch.completed_at = datetime.now(timezone.utc)
        batch.status = final_status
        batch.rows_inserted = rows_inserted
        batch.rows_rejected = total_rejected
        batch.error_detail = error_detail

        self.session.commit()
        self.session.refresh(batch)

        logger.info(
            "market_data_csv_import_finished",
            batch_id=str(batch.id),
            file_name=file_name,
            checksum=checksum,
            status=final_status,
            rows_read=batch.rows_read,
            rows_inserted=rows_inserted,
            rows_idempotent=rows_updated_or_unchanged,
            rows_rejected=total_rejected,
        )

        response = ImportBatchResponse.model_validate(batch)
        response.source_name = source.name
        return response

    def get_import_batch(self, batch_id: uuid.UUID) -> ImportBatchResponse:
        """Lấy thông tin chi tiết một lô import theo ID."""
        batch = self.session.get(ImportBatch, batch_id)
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy lô import với ID '{batch_id}'.",
            )
        source_name: Optional[str] = None
        if batch.source_id:
            source = self.session.get(DataSource, batch.source_id)
            source_name = source.name if source else None

        res = ImportBatchResponse.model_validate(batch)
        res.source_name = source_name
        return res

    # ------------------------------------------------------------------
    # Truy vấn Lịch sử Giá OHLCV & Tổng quan Thị trường
    # ------------------------------------------------------------------

    def get_stock_history(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 500,
    ) -> StockHistoryResponse:
        """Truy vấn chuỗi giá OHLCV theo symbol và khoảng ngày kèm thông tin nguồn dữ liệu."""
        normalized_symbol = symbol.strip().upper()
        stock = self.session.scalar(select(Stock).where(Stock.symbol == normalized_symbol))
        if not stock:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy mã cổ phiếu '{normalized_symbol}'.",
            )

        stmt = (
            select(DailyPrice, DataSource.name.label("source_name"))
            .join(DataSource, DailyPrice.source_id == DataSource.id)
            .where(DailyPrice.stock_id == stock.id)
        )

        if start_date is not None:
            stmt = stmt.where(DailyPrice.trading_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(DailyPrice.trading_date <= end_date)

        stmt = stmt.order_by(DailyPrice.trading_date.asc()).limit(limit)
        results = self.session.execute(stmt).all()

        items: List[DailyPriceItemResponse] = []
        for price_obj, src_name in results:
            items.append(
                DailyPriceItemResponse(
                    id=price_obj.id,
                    stock_id=price_obj.stock_id,
                    source_id=price_obj.source_id,
                    source_name=src_name,
                    import_batch_id=price_obj.import_batch_id,
                    trading_date=price_obj.trading_date,
                    open=price_obj.open,
                    high=price_obj.high,
                    low=price_obj.low,
                    close=price_obj.close,
                    adjusted_close=price_obj.adjusted_close,
                    volume=price_obj.volume,
                    created_at=price_obj.created_at,
                )
            )

        return StockHistoryResponse(
            symbol=stock.symbol,
            exchange=stock.exchange,
            company_name=stock.company_name,
            start_date=start_date,
            end_date=end_date,
            total_records=len(items),
            items=items,
        )

    def get_market_overview(self) -> MarketOverviewResponse:
        """Tổng hợp thống kê nhanh về dữ liệu thị trường và các lô import gần nhất."""
        total_stocks = int(self.session.scalar(select(func.count()).select_from(Stock)) or 0)
        active_stocks = int(
            self.session.scalar(
                select(func.count()).select_from(Stock).where(Stock.is_active.is_(True))
            )
            or 0
        )
        total_prices = int(self.session.scalar(select(func.count()).select_from(DailyPrice)) or 0)
        latest_date = self.session.scalar(select(func.max(DailyPrice.trading_date)))
        sources_count = int(self.session.scalar(select(func.count()).select_from(DataSource)) or 0)

        recent_batches = self.session.scalars(
            select(ImportBatch).order_by(ImportBatch.started_at.desc()).limit(5)
        ).all()

        return MarketOverviewResponse(
            total_stocks=total_stocks,
            active_stocks=active_stocks,
            total_daily_price_records=total_prices,
            latest_trading_date=latest_date,
            data_sources_count=sources_count,
            recent_import_batches=[ImportBatchResponse.model_validate(b) for b in recent_batches],
        )

    def sync_real_market_data(self, payload: SyncRealMarketRequest) -> SyncRealMarketResponse:
        """
        Đồng bộ dữ liệu lịch sử & giá mới nhất thực tế của chứng khoán Việt Nam (VNDirect DChart API):
        1. Nếu `purge_sample_data=True`: dọn sạch các bản ghi giá/chỉ báo/tín hiệu gắn nguồn SAMPLE và xóa tiền tố `[SAMPLE]` trên bảng `stocks`.
        2. Tải dữ liệu OHLCV thực tế cho danh sách mã (`FPT`, `HPG`, `VCB`, `ACB`, `MBB`, `TCB`, `SSI`, `MWG`, `CTG`, `VNM`...).
        3. Lưu idempotent vào `market.daily_prices` với nguồn `VNDIRECT_DCHART_REAL`.
        """
        started_at = datetime.now(timezone.utc)
        target_symbols = (
            [s.strip().upper() for s in payload.symbols if s.strip()]
            if payload.symbols
            else list(DEFAULT_REAL_VN_STOCKS.keys())
        )

        if payload.purge_sample_data:
            # Xóa các tín hiệu/proposal cũ chưa khớp và dữ liệu giá từ nguồn SAMPLE
            self.session.execute(delete(Approval).where(Approval.proposal_id.in_(
                select(TradeProposal.id).where(TradeProposal.status.in_(["PendingApproval", "Expired", "Rejected", "Blocked"]))
            )))
            self.session.execute(
                delete(TradeProposal).where(
                    TradeProposal.status.in_(["PendingApproval", "Expired", "Rejected", "Blocked"])
                )
            )
            self.session.execute(delete(AiReport))
            self.session.execute(delete(StockSignal))
            self.session.execute(delete(TechnicalIndicator))
            self.session.execute(delete(BacktestTrade))

            sample_sources = self.session.scalars(
                select(DataSource.id).where(DataSource.name.ilike("%SAMPLE%"))
            ).all()
            if sample_sources:
                self.session.execute(
                    delete(DailyPrice).where(DailyPrice.source_id.in_(sample_sources))
                )
                self.session.execute(
                    delete(ImportBatch).where(ImportBatch.source_id.in_(sample_sources))
                )
                self.session.execute(
                    delete(DataSource).where(DataSource.id.in_(sample_sources))
                )

            # Cập nhật lại tên công ty thật cho toàn bộ các mã trong bảng stocks
            for st in self.session.scalars(select(Stock)).all():
                if st.symbol in DEFAULT_REAL_VN_STOCKS:
                    exch, real_name, real_sec = DEFAULT_REAL_VN_STOCKS[st.symbol]
                    st.exchange = exch
                    st.company_name = real_name
                    st.sector = real_sec
                elif st.company_name and st.company_name.startswith("[SAMPLE]"):
                    st.company_name = st.company_name.replace("[SAMPLE]", "").strip()
            self.session.flush()

        source = self.get_or_create_data_source(
            source_name="VNDIRECT_DCHART_REAL",
            provider_type="HTTP_CHART_API",
            license_notes="Dữ liệu OHLCV thực tế từ cổng biểu đồ chứng khoán Việt Nam (VNDirect DChart) phục vụ nghiên cứu cá nhân.",
        )

        batch = ImportBatch(
            source_id=source.id,
            file_name=f"live_sync_{','.join(target_symbols[:5])}.json",
            checksum=f"LIVE_SYNC_{int(started_at.timestamp())}",
            started_at=started_at,
            status="PROCESSING",
            rows_read=0,
            rows_inserted=0,
            rows_rejected=0,
        )
        self.session.add(batch)
        self.session.flush()

        live_provider = VnMarketLiveHttpProvider()
        stock_cache: Dict[str, Stock] = {
            s.symbol: s for s in self.session.scalars(select(Stock)).all()
        }

        symbols_synced: List[str] = []
        errors: Dict[str, str] = {}
        total_upserted = 0
        latest_date: Optional[date] = None

        for sym in target_symbols:
            try:
                bars = live_provider.fetch_symbol_daily_bars(
                    symbol=sym,
                    lookback_days=payload.lookback_days,
                )
                if not bars:
                    errors[sym] = "EMPTY_RESPONSE"
                    continue
            except Exception as exc:
                errors[sym] = str(exc)
                continue

            stock = stock_cache.get(sym)
            meta = DEFAULT_REAL_VN_STOCKS.get(sym, ("HOSE", f"CTCP {sym}", "Cổ phiếu niêm yết"))
            if stock is None:
                stock = Stock(
                    symbol=sym,
                    exchange=meta[0],
                    company_name=meta[1],
                    sector=meta[2],
                    is_active=True,
                )
                self.session.add(stock)
                self.session.flush()
                stock_cache[sym] = stock
            else:
                stock.exchange = meta[0]
                stock.company_name = meta[1]
                stock.sector = meta[2]

            existing_by_date = {
                dp.trading_date: dp
                for dp in self.session.scalars(
                    select(DailyPrice).where(
                        DailyPrice.stock_id == stock.id,
                        DailyPrice.source_id == source.id,
                    )
                ).all()
            }

            for b in bars:
                if latest_date is None or b.trading_date > latest_date:
                    latest_date = b.trading_date
                existing_dp = existing_by_date.get(b.trading_date)
                if existing_dp is None:
                    self.session.add(
                        DailyPrice(
                            stock_id=stock.id,
                            source_id=source.id,
                            import_batch_id=batch.id,
                            trading_date=b.trading_date,
                            open=b.open,
                            high=b.high,
                            low=b.low,
                            close=b.close,
                            adjusted_close=b.adjusted_close,
                            volume=b.volume,
                        )
                    )
                else:
                    existing_dp.open = b.open
                    existing_dp.high = b.high
                    existing_dp.low = b.low
                    existing_dp.close = b.close
                    existing_dp.adjusted_close = b.adjusted_close
                    existing_dp.volume = b.volume
                    existing_dp.import_batch_id = batch.id
                total_upserted += 1

            symbols_synced.append(sym)

        batch.completed_at = datetime.now(timezone.utc)
        batch.rows_read = total_upserted
        batch.rows_inserted = total_upserted
        batch.rows_rejected = len(errors)
        batch.status = "COMPLETED" if symbols_synced else "FAILED"
        batch.error_detail = {"errors": errors, "symbols_synced": symbols_synced}

        self.session.commit()
        return SyncRealMarketResponse(
            batch_id=batch.id,
            source_name=source.name,
            symbols_synced=symbols_synced,
            rows_inserted_or_updated=total_upserted,
            latest_trading_date=latest_date,
            sample_records_purged=payload.purge_sample_data,
            errors=errors,
        )
