import os
import sqlite3
import requests
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

MARKET_DB_PATH = os.path.join("data", "market_data.db")
SYMBOLS_CSV_PATH = os.path.join("data", "symbols.csv")

SSI_URL = "https://iboard-api.ssi.com.vn/statistics/company/ssmi/stock-info"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}


def init_db():
    conn = sqlite3.connect(MARKET_DB_PATH)

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historical_ohlcv (
            symbol TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (symbol, date)
        )
    """)

    conn.commit()
    conn.close()


def fetch_and_save_symbol(symbol):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180)

        params = {
            "symbol": symbol,
            "page": 1,
            "pageSize": 1000,
            "fromDate": start_date.strftime("%d/%m/%Y"),
            "toDate": end_date.strftime("%d/%m/%Y"),
        }

        response = requests.get(
            SSI_URL,
            params=params,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        result = response.json()

        if result.get("code") != "SUCCESS":
            print(f"⚠️ {symbol}: API trả về lỗi: {result}")
            return False

        data = result.get("data", [])

        if not data:
            print(f"⚠️ {symbol}: Không có dữ liệu")
            return False

        rows = []

        for item in data:
            rows.append((
                symbol.upper(),
                pd.to_datetime(
                    item["tradingDate"],
                    dayfirst=True
                ).strftime("%Y-%m-%d"),
                float(item["open"]),
                float(item["high"]),
                float(item["low"]),
                float(item["close"]),
                float(item["volume"]),
            ))

        conn = sqlite3.connect(MARKET_DB_PATH)

        conn.executemany("""
            INSERT INTO historical_ohlcv
            (symbol, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, date)
            DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume
        """, rows)

        conn.commit()
        conn.close()

        return True

    except Exception as e:
        print(f"❌ {symbol}: {type(e).__name__}: {e}")
        return False


def main():
    print("🚀 Bắt đầu cập nhật dữ liệu từ SSI iBoard...")

    init_db()

    if os.path.exists(SYMBOLS_CSV_PATH):

        df_sym = pd.read_csv(SYMBOLS_CSV_PATH)

        col = (
            "symbol"
            if "symbol" in df_sym.columns
            else df_sym.columns[0]
        )

        symbols = [
            str(s).upper().strip()
            for s in df_sym[col].dropna().unique()
        ]

    else:
        print("❌ Không tìm thấy file data/symbols.csv!")
        return

    print(
        f"📊 Tìm thấy {len(symbols)} mã cổ phiếu. "
        "Đang tải dữ liệu từ SSI..."
    )

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(
            executor.map(fetch_and_save_symbol, symbols)
        )

    success_count = sum(results)

    print(
        f"✅ Hoàn tất! "
        f"{success_count}/{len(symbols)} mã đã được cập nhật."
    )


if __name__ == "__main__":
    main()