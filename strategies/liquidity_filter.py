import json
import sqlite3
from pathlib import Path

import pandas as pd


# ============================================================
# 1. CẤU HÌNH
# ============================================================

DB_PATH = Path("data/market_data.db")
WATCHLIST_PATH = Path("data/watch_list.json")

TABLE_NAME = "historical_ohlcv"

LOOKBACK_DAYS = 20
MIN_TURNOVER_VND = 5_000_000_000

# Dữ liệu giá đang tính theo đơn vị nghìn đồng
PRICE_UNIT_MULTIPLIER = 1000


# ============================================================
# 2. ĐỌC WATCHLIST
# ============================================================

def load_watchlist():
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Trường hợp: {"symbols": ["FPT", "VCB", ...]}
    if isinstance(data, dict):
        data = data.get("symbols", [])

    # Trường hợp: ["FPT", "VCB", ...] -> chuẩn hóa thành dict rỗng để đồng nhất xử lý
    if all(isinstance(item, str) for item in data):
        return [{"ticker": s} for s in data]

    # Trường hợp mỗi phần tử là dict đầy đủ (từ FA) -> GIỮ NGUYÊN, không rút gọn
    if all(isinstance(item, dict) for item in data):
        records = []
        for item in data:
            symbol = item.get("symbol") or item.get("ticker") or item.get("code")
            if symbol:
                rec = dict(item)          # copy nguyên dict gốc
                rec["ticker"] = symbol    # đảm bảo luôn có key "ticker" chuẩn
                records.append(rec)
        return records

    return []


# ============================================================
# 3. TÍNH TURNOVER TRUNG BÌNH 20 PHIÊN
# ============================================================

def calculate_turnover(symbol):
    query = f"""
        SELECT date, close, volume
        FROM {TABLE_NAME}
        WHERE symbol = ?
        ORDER BY date DESC
        LIMIT ?
    """

    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            query,
            conn,
            params=(symbol, LOOKBACK_DAYS)
        )

    if df.empty:
        return None

    # Loại dữ liệu thiếu
    df = df.dropna(subset=["close", "volume"])

    if df.empty:
        return None

    # Turnover mỗi phiên
    df["turnover"] = (
        df["close"]
        * df["volume"]
        * PRICE_UNIT_MULTIPLIER
    )

    # Trung bình 20 phiên
    avg_turnover = df["turnover"].mean()

    return {
        "symbol": symbol,
        "avg_turnover": avg_turnover,
        "sessions": len(df),
        "latest_date": df["date"].max()
    }


# ============================================================
# 4. LỌC THANH KHOẢN
# ============================================================

def run_liquidity_filter(records):
    results = []
    passed = []

    for rec in records:
        symbol = rec["ticker"]
        result = calculate_turnover(symbol)

        if result is None:
            continue

        results.append(result)

        if result["avg_turnover"] >= MIN_TURNOVER_VND:
            passed.append(rec)   # <-- giữ nguyên cả dict, không chỉ symbol

    return results, passed


# ============================================================
# 5. GHI WATCHLIST MỚI
# ============================================================

def save_watchlist(symbols):

    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(
            symbols,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# 6. MAIN
# ============================================================

def main():
    ...
    records = load_watchlist()          # đổi tên biến cho rõ nghĩa: records thay vì symbols

    print(f"Tổng số mã đầu vào: {len(records)}")
    print(f"Ngưỡng Turnover TB20: {MIN_TURNOVER_VND / 1e9:.0f} tỷ VNĐ")
    print()

    results, passed = run_liquidity_filter(records)

    print(f"Có dữ liệu: {len(results)}/{len(records)} mã")
    print(f"Đạt thanh khoản: {len(passed)} mã")
    print(f"Bị loại: {len(records) - len(passed)} mã")
    ...

    print("CÁC MÃ ĐẠT LIQUIDITY:")
    for rec in passed:
        symbol = rec["ticker"]
        result = next(x for x in results if x["symbol"] == symbol)
        print(f"  {symbol:<8} {result['avg_turnover'] / 1e9:>8.2f} tỷ/ngày")

    save_watchlist(passed)
    ...

    print()
    print("=" * 60)
    print(f"Đã ghi: {WATCHLIST_PATH}")
    print(f"Watch list mới: {len(passed)} mã")
    print("=" * 60)


if __name__ == "__main__":
    main()