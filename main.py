import os
import sys
import logging
from dotenv import load_dotenv


from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)

# Import các handler xử lý từ bot/handlers.py (Đã xóa backtest_command)
from bot.handlers import (
    start_command,
    help_command,
    stock_command,
    portfolio_command,
    today_command,
    watchlist_command,
    sector_command,
    alert_command,            # Lệnh /alert
    check_market_alerts_job,  # Job quét giá & cảnh báo
    handle_button_click,
    handle_text_ticker,
)

# Cấu hình logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Tải biến môi trường (.env)
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def post_init_setup(application: Application):
    """
    Hàm khởi tạo tự động chạy sau khi Bot sẵn sàng:
    1. Thiết lập Menu gợi ý lệnh trên Telegram UI.
    2. Kích hoạt JobQueue quét giá & vi phạm Cắt lỗ / Chốt lời.
    """
    # 1. Đăng ký danh sách Menu gợi ý lệnh (Đã loại bỏ /backtest)
    commands = [
        ("stock", "Tra cứu tín hiệu & phân tích 1 mã (VD: /stock FPT)"),
        ("today", "Tín hiệu MUA/BÁN phát hiện trong ngày"),
        ("watchlist", "Danh sách cổ phiếu đạt chuẩn FA (Lớp 1 & 2)"),
        ("sector", "Phân tích sức mạnh & dòng tiền nhóm ngành"),
        ("alert", "Đặt cảnh báo giá tự do (VD: /alert HPG > 28.5)"),
        ("portfolio", "Danh mục tài khoản đang nắm giữ"),
        ("help", "Hướng dẫn sử dụng Bot")
    ]
    await application.bot.set_my_commands(commands)
    logger.info("✅ Đã thiết lập Menu gợi ý lệnh thành công trên Telegram!")

    # 2. Kích hoạt JobQueue quét cảnh báo giá + vi phạm SL/TP (chạy mỗi 2 phút)
    if application.job_queue:
        application.job_queue.run_repeating(
            check_market_alerts_job, 
            interval=120, 
            first=10
        )
        logger.info("⏰ Đã kích hoạt JobQueue quét cảnh báo giá Realtime (2 phút/lần)!")


def main():
    if not TOKEN:
        logger.error("❌ LỖI: Chưa cài đặt TELEGRAM_BOT_TOKEN trong file .env!")
        sys.exit(1)

    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0
    )

    app = (
        Application.builder()
        .token(TOKEN)
        .request(request)
        .post_init(post_init_setup)
        .build()
    )

    # Đăng ký các CommandHandler (Đã xóa /backtest)
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("portfolio", portfolio_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("watchlist", watchlist_command))
    app.add_handler(CommandHandler("sector", sector_command))
    app.add_handler(CommandHandler("alert", alert_command))

    # Đăng ký CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(handle_button_click))

    # Đăng ký MessageHandler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_ticker))

    logger.info("🚀 Telegram Bot đã khởi chạy thành công và đang lắng nghe...")
    
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()