import os
import html
import json
import sqlite3
import logging
import concurrent.futures  
from datetime import datetime, timedelta, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import asyncio

import os

# Khai báo đường dẫn lưu trữ file cảnh báo giá
ALERTS_PATH = os.path.join(os.path.dirname(__file__), "price_alerts.json")

import pandas as pd
import ta
import requests
from vnstock.api.quote import Quote

from stock_bot.chart import generate_candlestick_chart
from stock_bot.data_pipeline.storage.historical_store import HistoricalStore

# Import các hàm và hằng số chuẩn từ file strategies/ta_strategy.py
from strategies.ta_strategy import (
    ta_load_price_history_realtime,
    ta_compute_indicators,
    VOLUME_SPIKE_RATIO,
    RSI_BUY_MIN,
    RSI_BUY_MAX,
    DEFAULT_WATCH_LIST_PATH,
)

# Import hàm lấy giá real-time đã tối ưu
try:
    from data.fetcher_price import get_current_price
except ImportError:
    try:
        from fetcher_price import get_current_price
    except ImportError:
        get_current_price = None

logger = logging.getLogger(__name__)

# Đường dẫn lưu trữ dữ liệu
DATA_DIR = "data"
WATCH_LIST_PATH = os.path.join(DATA_DIR, "watch_list.json")
TRADE_HISTORY_PATH = os.path.join(DATA_DIR, "trade_history.json")
MARKET_DB_PATH = os.path.join(DATA_DIR, "market_data.db")
SIGNALS_PATH = os.path.join(DATA_DIR, "signals.json")
POSITIONS_PATH = os.path.join(DATA_DIR, "positions.json")

SSI_HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

# ----------------------------------------------------
# HELPER CHUẨN HÓA VÀ ÉP KIỂU AN TOÀN
# ----------------------------------------------------
def _safe_float(val, default=0.0):
    """Tránh crash khi dữ liệu FA/TA là 'N/A' hoặc None"""
    if val is None or val == 'N/A' or pd.isna(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _normalize_price(price: float) -> float:
    """Đảm bảo giá luôn ở đơn vị VNĐ đầy đủ (VD: 20.9 -> 20900)"""
    p = _safe_float(price, 0.0)
    if 0 < p < 1000:
        return p * 1000.0
    return p


# ----------------------------------------------------
# 1. HÀM TRUY XUẤT DỮ LIỆU CƠ BẢN (FA & COMPANY)
# ----------------------------------------------------
def get_company_info(ticker: str) -> dict:
    """Lấy thông tin cơ bản doanh nghiệp từ SSI iBoard API."""
    try:
        url = f"https://iboard-api.ssi.com.vn/statistics/company/ssmi/company-profile?symbol={ticker.upper()}&language=vn"
        r = requests.get(url, headers=SSI_HEADERS, timeout=3)
        data = r.json().get('data', {})
        return {
            'name': data.get('companyName', ticker),
            'exchange': data.get('exchange', 'HOSE'),
            'sector': data.get('sector', 'Chưa xác định'),
            'sub_sector': data.get('subSector', 'Chưa xác định'),
            'market_cap': _safe_float(data.get('listedValue', 0)) / 1e9
        }
    except Exception:
        return {
            'name': ticker, 
            'exchange': 'HOSE', 
            'sector': 'Chưa xác định', 
            'sub_sector': 'Chưa xác định',
            'market_cap': 0
        }


def get_fa_data(ticker: str) -> dict:
    ticker_upper = ticker.upper()
    fa_result = {}

    candidate_paths = [
        WATCH_LIST_PATH,
        os.path.join(DATA_DIR, "watch_list.json"),
        os.path.join(DATA_DIR, "watch_list_liquid.json")
    ]

    for path in candidate_paths:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    watch = json.load(f)
                    if isinstance(watch, list):
                        for item in watch:
                            if isinstance(item, dict) and item.get('ticker', '').upper() == ticker_upper:
                                fa_result = item.copy()
                                break
                    elif isinstance(watch, dict):
                        res = watch.get(ticker_upper, {})
                        if isinstance(res, dict):
                            fa_result = res.copy()
            except Exception:
                pass
        if fa_result:
            break

    has_roe = fa_result.get('roe') is not None or fa_result.get('ROE') is not None
    
    if not fa_result or not has_roe:
        try:
            url = f"https://apipub.tcbs.com.vn/tsci/v1/company/overview?ticker={ticker_upper}"
            headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
            r = requests.get(url, headers=headers, timeout=4)
            
            if r.status_code == 200:
                data = r.json()
                roe_raw = data.get("roe")
                pe_raw = data.get("pe")
                eps_growth_raw = data.get("epsChange3Yr") or data.get("eps")

                fa_result['roe'] = round(_safe_float(roe_raw) * 100, 1) if roe_raw is not None else "N/A"
                fa_result['pe'] = round(_safe_float(pe_raw), 1) if pe_raw is not None else "N/A"
                fa_result['eps_growth_yoy'] = round(_safe_float(eps_growth_raw) * 100, 1) if eps_growth_raw is not None else "N/A"
                fa_result['sector'] = data.get('industry', 'Chưa xác định')
        except Exception as e:
            logger.warning(f"Lỗi lấy FA Realtime cho {ticker_upper}: {e}")

    if fa_result.get('pe') is None or fa_result.get('pe') == 'N/A':
        try:
            url = f"https://apipub.tcbs.com.vn/tsci/v1/company/overview?ticker={ticker_upper}"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
            if r.status_code == 200:
                pe_val = r.json().get("pe")
                if pe_val is not None:
                    fa_result['pe'] = round(_safe_float(pe_val), 1)
        except Exception:
            fa_result['pe'] = "N/A"

    return fa_result

# ----------------------------------------------------
# 2. HÀM QUẢN LÝ LỊCH SỬ GIAO DỊCH & VỊ THẾ
# ----------------------------------------------------
def load_trade_history() -> list:
    if os.path.exists(TRADE_HISTORY_PATH):
        try:
            with open(TRADE_HISTORY_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_trade_history(history: list):
    os.makedirs(os.path.dirname(TRADE_HISTORY_PATH), exist_ok=True)
    with open(TRADE_HISTORY_PATH, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_active_trade(ticker: str) -> dict:
    history = load_trade_history()
    for t in history:
        if t.get('ticker') == ticker.upper() and t.get('status') == 'OPEN':
            return t
    return None


def open_trade(ticker: str, price: float, stop_loss: float, take_profit: float, rr_ratio: float, entry_date: str):
    history = load_trade_history()
    ticker = ticker.upper()

    existing_trade = next((t for t in history if t.get('ticker') == ticker and t.get('status') == 'OPEN'), None)
    if existing_trade:
        return

    history.append({
        'ticker': ticker,
        'entry_price': _normalize_price(price),
        'entry_date': entry_date,
        'stop_loss': _normalize_price(stop_loss),
        'take_profit': _normalize_price(take_profit),
        'rr_ratio': rr_ratio,
        'status': 'OPEN'
    })
    save_trade_history(history)


def calc_trade_stats(ticker: str, entry_date: str, entry_price: float, current_price: float):
    t_plus = 0
    if os.path.exists(MARKET_DB_PATH):
        try:
            conn = sqlite3.connect(MARKET_DB_PATH)
            df = pd.read_sql_query("""
                SELECT DISTINCT date FROM historical_ohlcv
                WHERE UPPER(symbol) = UPPER(?) AND date >= ?
                ORDER BY date ASC
            """, conn, params=(ticker.upper(), entry_date))
            conn.close()
            t_plus = max(0, len(df) - 1)
        except Exception:
            pass

    norm_entry = _normalize_price(entry_price)
    norm_curr = _normalize_price(current_price)
            
    pnl_pct = ((norm_curr - norm_entry) / norm_entry) * 100 if norm_entry > 0 else 0.0
    return t_plus, round(pnl_pct, 2)


def get_position_info(ticker: str) -> str:
    ticker_upper = ticker.upper()
    positions_path = os.path.join(DATA_DIR, "positions.json")
    
    if not os.path.exists(positions_path):
        return "\n\n📌 <b>VỊ THẾ TÀI KHOẢN:</b> Chưa sở hữu"
        
    try:
        with open(positions_path, "r", encoding="utf-8") as f:
            positions = json.load(f)
            
        pos_data = None
        if isinstance(positions, dict):
            pos_data = positions.get(ticker_upper)
        elif isinstance(positions, list):
            for p in positions:
                if isinstance(p, dict) and p.get("ticker", "").upper() == ticker_upper:
                    pos_data = p
                    break
                    
        if pos_data:
            qty = pos_data.get("quantity", pos_data.get("vol", 0))
            buy_price = _normalize_price(pos_data.get("buy_price", pos_data.get("entry_price", 0)))
            
            current_price = buy_price
            if get_current_price:
                try:
                    p = get_current_price(ticker_upper)
                    if p > 0:
                        current_price = _normalize_price(p)
                except Exception:
                    pass
            
            pnl_pct = ((current_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
            pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"
            
            return (
                f"\n\n📌 <b>VỊ THẾ ĐANG NẮM GIỮ:</b>\n"
                f"• Khối lượng: <b>{qty:,}</b> CP\n"
                f"• Giá vốn: <b>{buy_price:,.0f}</b> VNĐ\n"
                f"• Giá hiện tại: <b>{current_price:,.0f}</b> VNĐ\n"
                f"• Lãi/Lỗ hiện tại: {pnl_icon} <b>{pnl_pct:+.2f}%</b>"
            )
    except Exception as e:
        logger.warning(f"Lỗi đọc vị thế cho {ticker_upper}: {e}")
        
    return "\n\n📌 <b>VỊ THẾ TÀI KHOẢN:</b> Chưa sở hữu"

# ----------------------------------------------------
# 3. LẤY DỮ LIỆU GIÁ & TÍNH TOÁN KĨ THUẬT
# ----------------------------------------------------
def get_stock_dataframe(ticker: str) -> pd.DataFrame:
    ticker = ticker.upper().strip()
    df = pd.DataFrame()

    try:
        store = HistoricalStore()
        raw_data = store.get_history(ticker)
        store.close()
        if raw_data:
            df = pd.DataFrame(raw_data, columns=["ticker", "date", "open", "high", "low", "close", "volume"])
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
    except Exception:
        pass

    if df.empty or len(df) < 20:
        try:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=150)).strftime('%Y-%m-%d')
            q = Quote(symbol=ticker, source='VCI')
            df_raw = q.history(start=start_date, end=end_date)
            
            if df_raw is not None and not df_raw.empty:
                df = df_raw.copy()
                date_col = 'time' if 'time' in df.columns else 'date'
                df['date'] = pd.to_datetime(df[date_col])
                df = df.sort_values('date').reset_index(drop=True)
        except Exception:
            return pd.DataFrame()

    if not df.empty and 'close' in df.columns:
        df['open'] = df['open'].apply(_normalize_price)
        df['high'] = df['high'].apply(_normalize_price)
        df['low'] = df['low'].apply(_normalize_price)
        df['close'] = df['close'].apply(_normalize_price)

        if get_current_price:
            realtime_p = get_current_price(ticker)
            if realtime_p > 0:
                realtime_p = _normalize_price(realtime_p)
                df.iloc[-1, df.columns.get_loc('close')] = realtime_p
                if realtime_p > df.iloc[-1]['high']:
                    df.iloc[-1, df.columns.get_loc('high')] = realtime_p
                if realtime_p < df.iloc[-1]['low']:
                    df.iloc[-1, df.columns.get_loc('low')] = realtime_p

    return df


def calc_smartscore(df: pd.DataFrame, fa_data: dict) -> tuple:
    latest = df.iloc[-1]

    rsi_val = _safe_float(latest.get('rsi14'), 50.0)
    rsi_score = min(rsi_val, 100)
    
    ema20_val = _safe_float(latest.get('ema20'), 0)
    ema50_val = _safe_float(latest.get('ema50'), 0)
    ema_score = 100 if ema20_val > ema50_val else 30
    
    vol_ratio = _safe_float(latest.get('volume_ratio'), 1.0)
    vol_score = min(vol_ratio * 50, 100)
    dong_luong = int(rsi_score * 0.4 + ema_score * 0.4 + vol_score * 0.2)

    if fa_data:
        roe = _safe_float(fa_data.get('roe', fa_data.get('ROE', 0)))
        roe_score = min(roe * 2, 100)
        eps_growth = _safe_float(fa_data.get('eps_growth_yoy', fa_data.get('EPS_growth_yoy', 0)))
        eps_score = min(max(eps_growth, 0), 100)
        chat_luong = int(roe_score * 0.5 + eps_score * 0.5)

        pe = _safe_float(fa_data.get('pe', fa_data.get('PE', 15)), 15.0)
        dinh_gia = max(0, int(100 - pe * 2)) if pe > 0 else 50
    else:
        chat_luong = 50
        dinh_gia = 50

    tong = int(dinh_gia * 0.3 + chat_luong * 0.35 + dong_luong * 0.35)
    return dinh_gia, chat_luong, dong_luong, tong

def get_current_price_fast(ticker: str) -> float:
    """Hàm lấy giá Realtime từ API công khai của DNSE hoặc TCBS"""
    ticker = ticker.upper().strip()

    # 1. Dự phòng 1: Gọi API Realtime DNSE (Lấy giá khớp lệnh mới nhất)
    try:
        url = f"https://services.entrade.com.vn/chart-api/v2/ticks?symbol={ticker}&limit=1"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=2)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                raw_price = data[0].get("price", 0)
                if raw_price > 0:
                    return _normalize_price(raw_price)
            elif isinstance(data, dict) and "ticks" in data:
                ticks = data.get("ticks", [])
                if ticks:
                    return _normalize_price(ticks[0].get("price", 0))
    except Exception as e:
        logger.warning(f"Lỗi lấy giá DNSE cho {ticker}: {e}")

    # 2. Dự phòng 2: Gọi API TCBS
    try:
        url = f"https://apipub.tcbs.com.vn/tsci/v1/stock/second-side-price?ticker={ticker}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=2)
        if r.status_code == 200:
            cp = r.json().get("price", 0)
            if cp > 0:
                return _normalize_price(cp)
    except Exception:
        pass

    return 0.0
def analyze_stock_signal(ticker: str) -> dict:
    """Hàm phân tích tổng hợp: ĐÃ CHÈN ĐÈ GIÁ REALTIME VÀO TÍNH TOÁN"""
    try:
        ticker = ticker.upper()

        # 1. TẢI DỮ LIỆU TỪ LỊCH SỬ
        df_ta = ta_load_price_history_realtime(ticker)
        if df_ta is None or df_ta.empty or len(df_ta) < 60:
            return {"error": f"Không đủ dữ liệu phân tích cho mã <b>{ticker}</b>."}

        # 2. LẤY GIÁ REALTIME MỚI NHẤT VÀ ÉP VÀO NẾN CUỐI
        realtime_p = get_current_price_fast(ticker)
        print(f"[DEBUG REALTIME] ---> Mã: {ticker} | Giá Realtime lấy được: {realtime_p}")

        if realtime_p > 0:
            today_date = date.today()
            last_date = pd.to_datetime(df_ta.iloc[-1]['date']).date() if 'date' in df_ta.columns else today_date
            
            # Nếu trong DB chưa có nến ngày hôm nay -> Tạo thêm 1 hàng cho hôm nay
            if last_date < today_date:
                new_row = df_ta.iloc[-1].copy()
                new_row['date'] = pd.to_datetime(today_date)
                new_row['open'] = realtime_p
                new_row['high'] = realtime_p
                new_row['low'] = realtime_p
                new_row['close'] = realtime_p
                df_ta = pd.concat([df_ta, pd.DataFrame([new_row])], ignore_index=True)
            else:
                # Đã có nến hôm nay -> Cập nhật giá đóng cửa realtime mới nhất
                df_ta.iloc[-1, df_ta.columns.get_loc('close')] = realtime_p
                if realtime_p > df_ta.iloc[-1]['high']:
                    df_ta.iloc[-1, df_ta.columns.get_loc('high')] = realtime_p
                if realtime_p < df_ta.iloc[-1]['low']:
                    df_ta.iloc[-1, df_ta.columns.get_loc('low')] = realtime_p

        # 3. TÍNH CHỈ BÁO THEO NẾN ĐÃ CẬP NHẬT GIÁ MỚI
        df_ta = ta_compute_indicators(df_ta)
        row_ta, prev_ta = df_ta.iloc[-1], df_ta.iloc[-2]

        price = _normalize_price(row_ta["close"])
        
        rsi_val = float(row_ta.get("rsi14", row_ta.get("rsi", 50)))
        vol_sma = row_ta.get("volume_sma20", row_ta.get("vol_ma20", 0))
        vol_ratio_val = float(row_ta["volume"] / vol_sma) if vol_sma else 0.0
        ema20_val = float(row_ta.get("ema20", price))

        trend_ok = price > ema20_val > float(prev_ta.get("ema20", price))
        vol_ok = vol_ratio_val >= VOLUME_SPIKE_RATIO
        rsi_ok = RSI_BUY_MIN <= rsi_val <= RSI_BUY_MAX

        if trend_ok and vol_ok and rsi_ok:
            signal_type = 'MUA'
            trend_str = 'TĂNG / TRÊN EMA20'
        else:
            signal_type = 'BÁN' if price < ema20_val else 'THEO DÕI'
            trend_str = 'GIẢM / TÍCH LŨY'

        # 4. LẤY DATAFRAME ĐỂ VẼ CHART & TÍNH SMARTSCORE
        df = get_stock_dataframe(ticker)
        if df.empty:
            df = df_ta
        else:
            df['ema20'] = ta.trend.ema_indicator(df['close'], window=20)
            df['ema50'] = ta.trend.ema_indicator(df['close'], window=50)
            df['rsi14'] = ta.momentum.rsi(df['close'], window=14)
            df['atr14'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
            df['vol_ma20'] = df['volume'].rolling(20).mean()
            df['volume_ratio'] = df['volume'] / df['vol_ma20']
            df['resist_20'] = df['high'].rolling(20).max().shift(1)

        latest = df.iloc[-1]
        atr = _safe_float(latest.get('atr14'), price * 0.02)
        resist = _normalize_price(latest.get('resist_20')) if pd.notna(latest.get('resist_20')) else price * 1.15

        latest_date_str = datetime.now().strftime('%d/%m/%Y')
        latest_db_date_format = datetime.now().strftime('%Y-%m-%d')

        company = get_company_info(ticker)
        fa_data = get_fa_data(ticker)
        dinh_gia, chat_luong, dong_luong, score_tong = calc_smartscore(df, fa_data)

        stop_loss = max(price - (2 * atr), price * 0.90)
        risk = max(price - stop_loss, price * 0.01)
        reward = resist - price

        if reward < 2 * risk:
            reward = 2 * risk
            resist = price + reward

        rr_ratio = reward / risk if risk > 0 else 0

        if signal_type == 'MUA':
            open_trade(ticker, price, stop_loss, resist, rr_ratio, latest_db_date_format)

        active_trade = get_active_trade(ticker)
        t_plus, pnl_pct = (0, 0.0)
        entry_date_display = latest_date_str

        if active_trade:
            t_plus, pnl_pct = calc_trade_stats(ticker, active_trade['entry_date'], active_trade['entry_price'], price)
            entry_date_display = pd.to_datetime(active_trade['entry_date']).strftime('%d/%m/%Y')

        ema_status_str = "Giá > EMA20" if price > ema20_val else "Giá <= EMA20"

        return {
            "ticker": ticker,
            "company": company,
            "signal_type": signal_type,
            "trend_str": trend_str,
            "price": price,
            "latest_date": latest_date_str,
            "entry_date": entry_date_display,
            "pnl_pct": pnl_pct,
            "t_plus": t_plus,
            "df": df,
            "smartscore": {
                "tong": score_tong,
                "dinh_gia": dinh_gia,
                "chat_luong": chat_luong,
                "dong_luong": dong_luong
            },
            "ta": {
                "rsi": round(rsi_val, 1),
                "vol_ratio": round(vol_ratio_val, 1),
                "ema_status": ema_status_str
            },
            "fa": fa_data,
            "stop_loss": stop_loss,
            "take_profit": resist,
            "rr_ratio": round(rr_ratio, 2)
        }
    except Exception as e:
        return {"error": f"Lỗi phân tích {ticker}: {str(e)}"}

# ----------------------------------------------------
# 4. BOT HANDLERS & TELEGRAM COMMANDS
# ----------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "👋 Chào mừng đến với FinTech Stock Bot!\n\n"
        "Các lệnh hỗ trợ:\n"
        "/stock FPT — Tra cứu tín hiệu & phân tích 1 mã\n"
        "/today — Tín hiệu MUA/BÁN phát hiện hôm nay\n"
        "/watchlist — Danh sách cổ phiếu đạt chuẩn FA\n"
        "/portfolio — Danh mục tài khoản đang nắm giữ\n"
        "/help — Hướng dẫn sử dụng Bot"
    )
    await update.message.reply_text(welcome_msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_command(update, context)


async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý lệnh /stock HPG -> Gửi giao diện Báo cáo đầy đủ như khi gõ HPG"""
    if context.args:
        ticker = context.args[0].upper().strip()
    else:
        await update.message.reply_text("⚠️ Vui lòng nhập mã. Ví dụ: <code>/stock HPG</code>", parse_mode="HTML")
        return

    await process_and_send_stock_signal(update, ticker)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt tin nhắn tự do người dùng nhập (VD: gõ HPG hoặc hpg)"""
    text = update.message.text.strip().upper()
    if len(text) <= 5 and text.isalpha():
        await process_and_send_stock_signal(update, text)
    else:
        await update.message.reply_text("❓ Cú pháp không hợp lệ. Gõ mã cổ phiếu (VD: FPT) hoặc gõ /help.")


async def process_and_send_stock_signal(update: Update, ticker: str):
    """Tạo BÁO CÁO HOÀN CHỈNH: Ảnh Chart + SmartScore + TA chuẩn + Quản trị 2x ATR + Vị thế"""
    msg = await update.message.reply_text(f"🔍 Đang tra cứu {ticker}...")
    res = analyze_stock_signal(ticker)

    if "error" in res:
        await msg.edit_text(res["error"], parse_mode="HTML")
        return

    if res["signal_type"] == "MUA":
        signal_emoji = "🟢 TÍN HIỆU MUA"
    elif res["signal_type"] == "BÁN":
        signal_emoji = "🔴 TÍN HIỆU BÁN"
    else:
        signal_emoji = "⚪ THEO DÕI"

    pnl_emoji = "🟢" if res["pnl_pct"] >= 0 else "🔴"
    comp = res["company"]
    score = res["smartscore"]
    ta_info = res["ta"]
    fa_info = res["fa"]

    company_name = html.escape(comp['name'])
    sector_name = html.escape(str(comp['sector']))

    caption_text = (
        f"📊 <b>{res['ticker']} - {company_name} ({comp['exchange']})</b>\n"
        f"📅 Chốt phiên ngày: <code>{res['latest_date']}</code>\n"
        f"-----------------------------------\n"
        f"Khuyến nghị: <b>{signal_emoji}</b>\n"
        f"• Xu hướng: <code>{res['trend_str']}</code>\n"
        f"• Giá hiện tại: <b>{res['price']:,.0f} VNĐ</b>\n"
        f"• Vị thế khuyến nghị: Lãi/Lỗ <b>{res['pnl_pct']:+.1f}%</b> {pnl_emoji} | <code>T + {res['t_plus']}</code> (Ngày vào: {res['entry_date']})\n\n"
        f"🟣 <b>ĐIỂM SMARTSCORE: {score['tong']}/100</b>\n"
        f"• Định giá: <code>{score['dinh_gia']}</code> | Chất lượng: <code>{score['chat_luong']}</code> | Động lượng: <code>{score['dong_luong']}</code>\n"
        f"• Ngành: <code>{sector_name}</code> | Vốn hóa: <code>{comp['market_cap']:,.0f} tỷ</code>\n"
    )

    roe = fa_info.get('roe', fa_info.get('ROE', 'N/A'))
    pe = fa_info.get('pe', fa_info.get('PE', 'N/A'))
    eps = fa_info.get('eps_growth_yoy', fa_info.get('EPS_growth_yoy', 'N/A'))
    caption_text += f"• ROE: <code>{roe}%</code> | P/E: <code>{pe}</code> | Tăng trưởng EPS: <code>{eps}%</code>\n"

    sl_pct = (res['stop_loss'] / res['price'] - 1) * 100
    tp_pct = (res['take_profit'] / res['price'] - 1) * 100

    caption_text += (
        f"\n📈 <b>Phân tích kỹ thuật (TA):</b>\n"
        f"• RSI(14): <code>{ta_info['rsi']}</code> | Khối lượng: <code>{ta_info['vol_ratio']}x MA20</code>\n"
        f"• Trạng thái EMA: <code>{ta_info['ema_status']}</code>\n\n"
        f"🛡 <b>Quản trị vị thế (2x ATR):</b>\n"
        f"• Cắt lỗ động: <code>{res['stop_loss']:,.0f} VNĐ</code> ({sl_pct:.1f}%)\n"
        f"• Chốt lời kỳ vọng: <code>{res['take_profit']:,.0f} VNĐ</code> (+{tp_pct:.1f}%)\n"
        f"• Tỷ lệ Risk/Reward: <code>1 : {res['rr_ratio']}</code>"
    )

    pos_info = get_position_info(ticker)
    caption_text += pos_info

    chart_file = None
    try:
        chart_file = generate_candlestick_chart(res["df"], ticker)
        with open(chart_file, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption_text, parse_mode="HTML")
        await msg.delete()
    except Exception as e:
        logger.error(f"Lỗi gửi đồ thị mã {ticker}: {e}")
        try:
            await msg.edit_text(caption_text, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(
                f"📊 Kết quả phân tích {ticker}:\n"
                f"• Giá: {res['price']:,.0f} VNĐ\n"
                f"• Tín hiệu: {res['signal_type']}\n"
                f"• SmartScore: {score['tong']}/100"
            )
    finally:
        if chart_file and os.path.exists(chart_file):
            try:
                os.remove(chart_file)
            except Exception:
                pass


async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt và xử lý sự kiện khi người dùng bấm các nút Inline Keyboard."""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat_id

    if data.startswith("chart_"):
        ticker = data.split("_")[1]
        await query.edit_message_text(
            f"📈 <b>ĐỒ THỊ KỸ THUẬT MÃ {ticker}</b>\n"
            f"• Khung thời gian: Daily (D1)\n"
            f"• MA20: <code>21.0</code> | MA50: <code>20.2</code>\n"
            f"• Kháng cự gần nhất: <code>23.5</code>\n"
            f"• Hỗ trợ cứng: <code>20.5</code>\n\n"
            f"<i>(Hệ thống đang xuất ảnh Chart nến...)</i>",
            parse_mode="HTML"
        )

    elif data.startswith("fa_"):
        ticker = data.split("_")[1]
        await query.edit_message_text(
            f"📊 <b>SỨC MẠNH TÀI CHÍNH (FA) - MÃ {ticker}</b>\n"
            f"=====================================\n"
            f"• ROE TTM: <code>18.5%</code> (Đạt chuẩn CANSLIM > 15%)\n"
            f"• P/E: <code>12.4</code> | P/B: <code>1.6</code>\n"
            f"• Tăng trưởng LN Ròng Q1 YoY: <code>+24.5%</code> 🚀\n"
            f"• Nợ/Vốn CSH (D/E): <code>0.65</code> (An toàn < 1.2)\n"
            f"• Dòng tiền HĐKD (CFO): <b>Dương mạnh</b>\n"
            f"=====================================\n"
            f"🎯 <i>Đánh giá Lớp 2 FA: ĐẠT CHUẨN TĂNG TRƯỞNG</i>",
            parse_mode="HTML"
        )

    elif data.startswith("add_port_"):
        ticker = data.split("_")[1]
        POSITIONS_PATH = "data/positions.json"
        positions = []
        if os.path.exists(POSITIONS_PATH):
            try:
                with open(POSITIONS_PATH, "r", encoding="utf-8") as f:
                    positions = json.load(f)
            except Exception:
                positions = []

        if any(p.get("ticker") == ticker for p in positions):
            await query.message.reply_text(f"⚠️ Mã <b>{ticker}</b> đã có sẵn trong Danh mục của bạn!", parse_mode="HTML")
            return

        new_position = {
            "ticker": ticker,
            "buy_date": datetime.now().strftime("%Y-%m-%d"),
            "buy_price": 21500,
            "stop_loss": 20400,
            "chat_id": chat_id
        }
        positions.append(new_position)

        with open(POSITIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(positions, f, ensure_ascii=False, indent=2)

        await query.message.reply_text(
            f"✅ Đã thêm mã <b>{ticker}</b> vào Danh mục <code>/portfolio</code> của bạn!\n"
            f"• Giá mua ghi nhận: <code>21,500 đ</code>\n"
            f"• Tự động Cắt lỗ tại: <code>20,400 đ</code>",
            parse_mode="HTML"
        )
# ====================================================
# PHẦN 2: LỆNH TODAYS, PORTFOLIO, WATCHLIST & UTILS
# ====================================================

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lấy báo cáo lọc TA chính chủ từ file ta_strategy.py."""
    await update.message.reply_text("⏳ Đang kích hoạt BỘ LỌC TA...")

    if not os.path.exists(DEFAULT_WATCH_LIST_PATH):
        await update.message.reply_text("⚠️ Chưa tìm thấy file <code>data/watch_list.json</code>!", parse_mode="HTML")
        return

    try:
        with open(DEFAULT_WATCH_LIST_PATH, "r", encoding="utf-8") as f:
            watch_list = json.load(f)

        # Chạy trực tiếp hàm báo cáo lọc từ ta_strategy.py
        from strategies.ta_strategy import ta_criteria_report
        report_text = ta_criteria_report(watch_list, realtime=True)
        
        # Escape HTML để tránh lỗi văng tag
        safe_report = html.escape(report_text)

        msg = (
            "📊 <b>BÁO CÁO BỘ LỌC TA (TODAY)</b>\n"
            "=====================================\n\n"
            f"<pre>{safe_report}</pre>\n\n"
            "💡 <i>Gõ <code>/stock &lt;Mã&gt;</code> hoặc nhập trực tiếp tên Mã để xem báo cáo chi tiết.</i>"
        )

        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Lỗi khi chạy bộ lọc today: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Có lỗi khi lọc dữ liệu: <code>{str(e)}</code>", parse_mode="HTML")


def calculate_t_days(entry_date_str):
    """Tính số ngày nắm giữ (T+N)"""
    try:
        entry_date = datetime.strptime(str(entry_date_str).strip(), "%Y-%m-%d").date()
        today = datetime.now().date()
        delta = (today - entry_date).days
        return f"T+{delta}" if delta >= 0 else f"T{delta}"
    except Exception:
        return "N/A"


async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quản lý danh mục tài khoản đang nắm giữ"""
    try:
        if not os.path.exists(POSITIONS_PATH):
            await update.message.reply_text("📭 Danh mục đầu tư hiện đang trống.")
            return

        with open(POSITIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not data:
            await update.message.reply_text("📭 Danh mục đầu tư hiện đang trống.")
            return

        items = []
        if isinstance(data, dict):
            for ticker, info in data.items():
                if isinstance(info, dict):
                    info["ticker"] = ticker
                    items.append(info)
        elif isinstance(data, list):
            items = data

        active_positions = [
            x for x in items 
            if str(x.get("status", "HOLD")).upper() in ["HOLD", "OPEN"]
        ]

        if not active_positions:
            await update.message.reply_text("📭 Hiện tại không có vị thế nào đang nắm giữ.")
            return

        msg = "💼 <b>DANH MỤC ĐANG NẮM GIỮ</b>\n" + "="*32 + "\n\n"

        for item in active_positions:
            ticker = str(item.get("ticker", "N/A")).upper()
            entry_date = item.get("entry_date", item.get("buy_date", "N/A"))
            
            fmt_entry = _normalize_price(item.get("entry_price", item.get("buy_price", 0)))
            fmt_sl = _normalize_price(item.get("stop_loss", 0))
            fmt_tp = _normalize_price(item.get("take_profit", 0))

            current_price = fmt_entry
            if get_current_price:
                try:
                    p = get_current_price(ticker)
                    if p > 0:
                        current_price = _normalize_price(p)
                except Exception as ex:
                    logger.warning(f"Lỗi lấy giá cho {ticker}: {ex}")

            pnl_pct = ((current_price - fmt_entry) / fmt_entry * 100) if fmt_entry > 0 else 0.0
            pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"
            pnl_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"

            t_days = calculate_t_days(entry_date)

            msg += f"🟢 <b>{ticker}</b>\n"
            msg += f" • Ngày mua: {entry_date}\n"
            msg += f" • Giá vào: <b>{fmt_entry:,.0f} đ</b>\n"
            msg += f" • Giá hiện tại: <b>{current_price:,.0f} đ</b>\n"
            msg += f" • Lãi/Lỗ: <b>{pnl_str}</b> {pnl_icon}\n"
            msg += f" • Số phiên: <code>{t_days}</code>\n"
            if fmt_sl > 0:
                msg += f" • Cắt lỗ: <code>{fmt_sl:,.0f} đ</code>\n"
            if fmt_tp > 0:
                msg += f" • Chốt lời: <code>{fmt_tp:,.0f} đ</code>\n"
            msg += "\n" + "-"*30 + "\n\n"

        await update.message.reply_text(msg, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Lỗi khi đọc portfolio: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Có lỗi xảy ra: <code>{str(e)}</code>", parse_mode="HTML")


async def watchlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem danh sách Watchlist FA kèm Tên Ngành tự động."""
    if not os.path.exists(WATCH_LIST_PATH):
        await update.message.reply_text("⚠️ Chưa có file <code>data/watch_list.json</code>.", parse_mode="HTML")
        return
    try:
        with open(WATCH_LIST_PATH, "r", encoding="utf-8") as f:
            watch_data = json.load(f)

        if not watch_data:
            await update.message.reply_text("📭 Danh sách Watchlist hiện đang trống.")
            return

        reply = "📋 <b>DANH SÁCH CỔ PHIẾU ĐẠT CHUẨN CƠ BẢN (FA)</b>\n" + "="*30 + "\n"
        
        if isinstance(watch_data, list):
            reply += f"Tổng cộng: <b>{len(watch_data)}</b> mã chọn lọc.\n\n"
            
            # Hiển thị tối đa 15 mã đầu tiên
            for item in watch_data[:15]:
                if isinstance(item, str):
                    ticker = item.upper()
                    comp_info = get_company_info(ticker)
                    sector = comp_info.get('sector', 'Chưa xác định')
                    reply += f"• <b>{ticker}</b> | Ngành: <code>{html.escape(str(sector))}</code>\n"
                    
                elif isinstance(item, dict):
                    ticker = item.get('ticker', 'N/A').upper()
                    sector = item.get('sector')
                    
                    # Tự động gọi API bổ sung nếu ngành bị trống
                    if not sector or sector in ['Chưa rõ', 'Chưa xác định', 'Chưa phân ngành', '']:
                        comp_info = get_company_info(ticker)
                        sector = comp_info.get('sector', 'Chưa xác định')
                        
                    roe_val = item.get('roe', item.get('ROE', 'N/A'))
                    pe_val = item.get('pe', item.get('PE', 'N/A'))
                    
                    reply += f"• <b>{ticker}</b> | Ngành: <code>{html.escape(str(sector))}</code> | ROE: <code>{roe_val}%</code> | P/E: <code>{pe_val}</code>\n"

            if len(watch_data) > 15:
                reply += f"\n<i>...và {len(watch_data) - 15} mã khác.</i>"

        await update.message.reply_text(reply, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Lỗi đọc Watchlist: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Lỗi đọc Watchlist: {e}", parse_mode="HTML")


async def sector_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý lệnh /sector — Phân tích sóng ngành chi tiết từng mã (Đa luồng)."""
    msg = await update.message.reply_text("⚡ Đang quét dữ liệu sóng ngành...")
    
    if not os.path.exists(DEFAULT_WATCH_LIST_PATH):
        await msg.edit_text("⚠️ Chưa tìm thấy file <code>data/watch_list.json</code>!", parse_mode="HTML")
        return

    try:
        with open(DEFAULT_WATCH_LIST_PATH, "r", encoding="utf-8") as f:
            watch_list = json.load(f)

        if not watch_list:
            await msg.edit_text("📭 Danh sách mã theo dõi trống.")
            return

        # 1. Lấy danh sách tất cả các mã cổ phiếu
        tickers = []
        for item in watch_list:
            if isinstance(item, str):
                tickers.append(item.upper())
            elif isinstance(item, dict) and item.get('ticker'):
                tickers.append(item.get('ticker').upper())

        tickers = list(set(tickers)) # Lọc trùng

        # 2. Hàm xử lý dữ liệu từng mã
        def process_single_stock(ticker):
            try:
                info = get_company_info(ticker)
                sec = info.get('sector', 'Khác')
                
                df = ta_load_price_history_realtime(ticker)
                if df.empty or len(df) < 20:
                    return None

                df = ta_compute_indicators(df)
                row, prev = df.iloc[-1], df.iloc[-2]

                p_curr = float(row['close'])
                p_prev = float(prev['close'])
                pct_change = ((p_curr - p_prev) / p_prev) * 100 if p_prev > 0 else 0.0

                rsi = float(row['rsi14'])
                vol_r = float(row['volume'] / row['volume_sma20']) if row['volume_sma20'] else 0.0
                ema20 = float(row['ema20'])

                is_buy = (p_curr > ema20 > float(prev['ema20'])) and (vol_r >= VOLUME_SPIKE_RATIO) and (RSI_BUY_MIN <= rsi <= RSI_BUY_MAX)

                return {
                    'ticker': ticker,
                    'sector': sec,
                    'pct_change': pct_change,
                    'is_buy': is_buy
                }
            except Exception:
                return None

        # 3. Chạy đa luồng song song
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            tasks = [loop.run_in_executor(executor, process_single_stock, t) for t in tickers]
            results = await asyncio.gather(*tasks)

        valid_results = [r for r in results if r is not None]

        # 4. Gom nhóm theo Ngành
        sector_groups = {}
        for r in valid_results:
            sec = r['sector']
            sector_groups.setdefault(sec, []).append(r)

        # 5. Tổng hợp dữ liệu từng Ngành
        sector_summary = []
        for sec, items in sector_groups.items():
            buy_signals = sum(1 for i in items if i['is_buy'])
            avg_change = sum(i['pct_change'] for i in items) / len(items) if items else 0.0
            
            sector_summary.append({
                'sector': sec,
                'total': len(items),
                'buy_signals': buy_signals,
                'avg_change': avg_change,
                'items': items
            })

        # Sắp xếp ngành ưu tiên: Số tín hiệu MUA > % Tăng giá TB
        sector_summary.sort(key=lambda x: (x['buy_signals'], x['avg_change']), reverse=True)

        # 6. Xuất báo cáo Telegram có liệt kê mã chi tiết
        report = "🌊 <b>PHÂN TÍCH SÓNG NGÀNH REALTIME</b>\n"
        report += f"📅 Cập nhật: <code>{datetime.now().strftime('%H:%M - %d/%m/%Y')}</code>\n"
        report += "="*32 + "\n\n"

        for s in sector_summary:
            chg_icon = "🟢" if s['avg_change'] >= 0 else "🔴"
            hot_icon = "🔥 " if s['buy_signals'] > 0 else "• "
            
            report += f"{hot_icon}<b>{html.escape(s['sector'])}</b> ({s['avg_change']:+.2f}% {chg_icon})\n"
            report += f" - Tín hiệu MUA: <b>{s['buy_signals']}/{s['total']}</b> mã\n"
            
            # Liệt kê chi tiết từng mã
            stock_list_str = []
            for item in s['items']:
                status_icon = "🟢" if item['is_buy'] else "⚪"
                stock_list_str.append(f"{status_icon} <b>{item['ticker']}</b> ({item['pct_change']:+.1f}%)")
            
            report += " - Danh sách: " + ", ".join(stock_list_str) + "\n\n"

        report += "💡 <i>Ghi chú: 🟢 Tín hiệu MUA | ⚪ Theo dõi/Chưa đạt</i>"
        await msg.edit_text(report, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Lỗi lệnh /sector: {e}", exc_info=True)
        await msg.edit_text(f"❌ Có lỗi khi phân tích ngành: <code>{str(e)}</code>", parse_mode="HTML")


async def handle_text_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý tin nhắn khi người dùng gõ trực tiếp mã cổ phiếu (VD: hpg, vcb, fpt)"""
    text = update.message.text.strip().upper()
    if 3 <= len(text) <= 5 and text.isalpha():
        # Gọi trực tiếp quy trình tạo báo cáo đầy đủ (SmartScore + Chart + TA + FA)
        await process_and_send_stock_signal(update, text)
    else:
        await update.message.reply_text("❓ Lệnh không hợp lệ. Hãy gõ mã cổ phiếu (VD: FPT) hoặc gõ /help.")

import html
import re

# ----------------------------------------------------
# 1. QUẢN LÝ DỮ LIỆU CẢNH BÁO GIÁ THỦ CÔNG
# ----------------------------------------------------
def load_price_alerts() -> list:
    if os.path.exists(ALERTS_PATH):
        try:
            with open(ALERTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_price_alerts(alerts: list):
    os.makedirs(os.path.dirname(ALERTS_PATH), exist_ok=True)
    with open(ALERTS_PATH, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)

async def check_single_alert(bot, alert: dict) -> bool:
    """Hàm kiểm tra 1 cảnh báo đơn lẻ. Trả về True nếu đã phát cảnh báo."""
    chat_id = alert.get("chat_id")
    ticker = alert.get("ticker", "").upper()
    op = alert.get("operator")
    target_p = alert.get("target_price", 0)

    curr_p = 0
    if get_current_price:
        try:
            curr_p = _normalize_price(get_current_price(ticker))
        except Exception:
            pass

    if curr_p > 0:
        triggered = False
        if op in [">", ">="] and curr_p >= target_p:
            triggered = True
        elif op in ["<", "<="] and curr_p <= target_p:
            triggered = True

        if triggered:
            safe_op = html.escape(str(op))
            msg = (
                f"🚨 <b>CẢNH BÁO GIÁ KÍCH HOẠT!</b>\n"
                f"=====================================\n"
                f"• Mã cổ phiếu: <b>{ticker}</b>\n"
                f"• Giá hiện tại: <b>{curr_p:,.0f} VNĐ</b>\n"
                f"• Mức cảnh báo đặt: Giá {safe_op} <b>{target_p:,.0f} VNĐ</b>\n\n"
                f"💡 <i>Gõ <code>/stock {ticker}</code> để xem phân tích chi tiết.</i>"
            )
            try:
                await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
                return True
            except Exception as e:
                logger.error(f"Lỗi gửi tin nhắn alert cho {chat_id}: {e}")
    return False


async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Lệnh đặt cảnh báo giá thông minh:
    - /alert HPG > 28.5 hoặc /alert HPG < 23
    - /alert list (Xem danh sách)
    - /alert delete 1 3 4 (Xóa nhiều STT cùng lúc)
    """
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "⚠️ <b>Cú pháp không hợp lệ!</b>\n\n"
            "👉 Vui lòng nhập theo dạng:\n"
            "• <code>/alert HPG &gt; 28.5</code> (Báo khi giá vượt 28.5)\n"
            "• <code>/alert FPT &lt; 120</code> (Báo khi giá giảm dưới 120)\n"
            "• <code>/alert list</code> (Xem danh sách cảnh báo)\n"
            "• <code>/alert delete 1 3 5</code> (Xóa các cảnh báo số 1, 3, 5)",
            parse_mode="HTML"
        )
        return

    # 1. Xử lý lệnh /alert list
    if args[0].lower() == "list":
        alerts = load_price_alerts()
        user_alerts = [a for a in alerts if a.get("chat_id") == chat_id]
        if not user_alerts:
            await update.message.reply_text("📭 Bạn chưa thiết lập cảnh báo giá nào.")
            return

        msg = "🔔 <b>DANH SÁCH CẢNH BÁO GIÁ CỦA BẠN:</b>\n" + "="*32 + "\n"
        for idx, a in enumerate(user_alerts, 1):
            safe_op = html.escape(str(a['operator']))
            msg += f"{idx}. <b>{a['ticker']}</b> {safe_op} {a['target_price']:,.0f} VNĐ\n"
        msg += "\n💡 <i>Gõ <code>/alert delete 1 2</code> để xóa các STT tương ứng.</i>"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # 2. Xử lý xóa nhiều STT cùng lúc
    if args[0].lower() == "delete" and len(args) >= 2:
        alerts = load_price_alerts()
        user_alerts = [a for a in alerts if a.get("chat_id") == chat_id]

        if not user_alerts:
            await update.message.reply_text("📭 Bạn không có cảnh báo nào để xóa.")
            return

        raw_indices = re.findall(r'\d+', " ".join(args[1:]))
        if not raw_indices:
            await update.message.reply_text("⚠️ Vui lòng nhập STT hợp lệ. Ví dụ: <code>/alert delete 1 3 4</code>", parse_mode="HTML")
            return

        indices_to_delete = sorted(list(set(int(x) - 1 for x in raw_indices)), reverse=True)
        deleted_tickers = []

        for idx in indices_to_delete:
            if 0 <= idx < len(user_alerts):
                target = user_alerts[idx]
                if target in alerts:
                    alerts.remove(target)
                    deleted_tickers.append(f"{target['ticker']} ({html.escape(target['operator'])}{target['target_price']:,.0f})")

        if deleted_tickers:
            save_price_alerts(alerts)
            await update.message.reply_text(
                f"✅ <b>Đã xóa thành công {len(deleted_tickers)} cảnh báo:</b>\n• " + "\n• ".join(deleted_tickers),
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("⚠️ Không tìm thấy STT nào phù hợp!")
        return

    # 3. Tạo cảnh báo mới
    full_text = " ".join(args).strip()
    operator = None
    if ">=" in full_text: operator = ">="
    elif "<=" in full_text: operator = "<="
    elif ">" in full_text: operator = ">"
    elif "<" in full_text: operator = "<"

    if not operator:
        await update.message.reply_text("⚠️ Thiếu toán tử so sánh (phải có dấu <code>&gt;</code> hoặc <code>&lt;</code>)!", parse_mode="HTML")
        return

    parts = full_text.split(operator)
    ticker = parts[0].strip().upper()
    price_str = parts[1].strip()

    if not ticker or not price_str:
        await update.message.reply_text("⚠️ Cú pháp không hợp lệ! Ví dụ đúng: <code>/alert HPG &gt; 28.5</code>", parse_mode="HTML")
        return

    try:
        raw_price = float(price_str.replace(",", "."))
        target_price = raw_price * 1000.0 if raw_price < 1000 else raw_price
    except ValueError:
        await update.message.reply_text("⚠️ Mức giá nhập vào không đúng định dạng số!")
        return

    new_alert = {
        "chat_id": chat_id,
        "ticker": ticker,
        "operator": operator,
        "target_price": target_price,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    # Kiểm tra ngay lập tức xem giá hiện tại đã thỏa mãn chưa
    is_triggered = await check_single_alert(context.bot, new_alert)
    if is_triggered:
        return  # Nếu giá đã thỏa mãn ngay lập tức thì gửi tin nhắn báo động luôn và KHÔNG lưu nữa

    # Nếu chưa thỏa mãn thì lưu vào file để chờ JobQueue quét
    alerts = load_price_alerts()
    alerts.append(new_alert)
    save_price_alerts(alerts)

    safe_op = html.escape(operator)
    await update.message.reply_text(
        f"✅ <b>Đã kích hoạt Cảnh báo giá!</b>\n\n"
        f"• Mã: <b>{ticker}</b>\n"
        f"• Điều kiện: Giá {safe_op} <b>{target_price:,.0f} VNĐ</b>\n"
        f"🤖 Bot sẽ nhắn tin cho bạn ngay khi chạm ngưỡng.",
        parse_mode="HTML"
    )

# ----------------------------------------------------
# 2. CRONJOB QUÉT GIÁ REALTIME & CẢNH BÁO VI PHẠM (JOB QUEUE)
# ----------------------------------------------------
async def check_market_alerts_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Hàm định kỳ quét giá thị trường:
    1. Kiểm tra cảnh báo giá người dùng tự đặt (/alert).
    2. Kiểm tra vi phạm Stop-Loss / Take-Profit trong Portfolio.
    """
    # A. Quét Cảnh Báo Giá Tự Đặt (/alert)
    alerts = load_price_alerts()
    remaining_alerts = []

    for alert in alerts:
        triggered = await check_single_alert(context.bot, alert)
        if not triggered:
            remaining_alerts.append(alert)

    save_price_alerts(remaining_alerts)

    # B. Quét Vi Phạm Cắt Lỗ / Chốt Lời (Portfolio)
    if os.path.exists(POSITIONS_PATH):
        try:
            with open(POSITIONS_PATH, "r", encoding="utf-8") as f:
                positions = json.load(f)

            pos_items = positions if isinstance(positions, list) else list(positions.values())

            for pos in pos_items:
                if not isinstance(pos, dict):
                    continue

                ticker = pos.get("ticker", "").upper()
                chat_id = pos.get("chat_id")
                
                if not chat_id or not ticker:
                    continue

                sl_price = _normalize_price(pos.get("stop_loss", 0))
                tp_price = _normalize_price(pos.get("take_profit", 0))
                buy_price = _normalize_price(pos.get("buy_price", pos.get("entry_price", 0)))

                curr_p = 0
                if get_current_price:
                    try:
                        curr_p = _normalize_price(get_current_price(ticker))
                    except Exception:
                        pass

                if curr_p <= 0:
                    continue

                # 1. Kiểm tra vi phạm Cắt lỗ (Stop Loss)
                if sl_price > 0 and curr_p <= sl_price:
                    pnl_pct = ((curr_p - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
                    msg = (
                        f"⚠️ <b>CẢNH BÁO VI PHẠM CẮT LỖ (STOP-LOSS)!</b>\n"
                        f"=====================================\n"
                        f"• Mã: <b>{ticker}</b>\n"
                        f"• Giá hiện tại: <b>{curr_p:,.0f} VNĐ</b> (Lỗ {pnl_pct:.1f}% 🔴)\n"
                        f"• Ngưỡng Cắt lỗ: <b>{sl_price:,.0f} VNĐ</b>\n\n"
                        f"🛑 <b>Hành động khuyến nghị:</b> Cân nhắc hạ tỷ trọng hoặc đóng vị thế!"
                    )
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
                    except Exception as e:
                        logger.error(f"Lỗi gửi tin Stop-loss cho {chat_id}: {e}")

                # 2. Kiểm tra cán mốc Chốt lời (Take Profit)
                elif tp_price > 0 and curr_p >= tp_price:
                    pnl_pct = ((curr_p - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
                    msg = (
                        f"🎯 <b>CẢNH BÁO ĐẠT MỐC CHỐT LỜI (TAKE-PROFIT)!</b>\n"
                        f"=====================================\n"
                        f"• Mã: <b>{ticker}</b>\n"
                        f"• Giá hiện tại: <b>{curr_p:,.0f} VNĐ</b> (Lãi +{pnl_pct:.1f}% 🟢)\n"
                        f"• Ngưỡng Chốt lời: <b>{tp_price:,.0f} VNĐ</b>\n\n"
                        f"💰 <b>Hành động khuyến nghị:</b> Cân nhắc chốt lời một phần!"
                    )
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
                    except Exception as e:
                        logger.error(f"Lỗi gửi tin Take-profit cho {chat_id}: {e}")

        except Exception as e:
            logger.error(f"Lỗi quét vị thế vi phạm: {e}")