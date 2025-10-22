import os
import asyncio
import logging
from typing import List, Dict
from dotenv import load_dotenv
from datetime import timedelta

import aiohttp
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from price_sources import fetch_prices_for_token
from compare_prices import compute_spreads, format_markdown

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DEFAULT_TOKENS = os.getenv("TOKENS", "BTC,ETH,SOL,BNB").split(",")
DEFAULT_THRESHOLD = float(os.getenv("THRESHOLD_PCT", "0.5"))
DEFAULT_INTERVAL = int(os.getenv("INTERVAL_SEC", "60"))
DEFAULT_EXCHANGES = [x.strip() for x in os.getenv("EXCHANGES", "binance,coinbase,kraken,kucoin,bybit,okx,bitstamp").split(",")]

# Per-chat settings
CHAT_SETTINGS: Dict[int, Dict] = {}

async def fetch_all_prices(session: aiohttp.ClientSession, tokens: List[str], exchanges: List[str]):
    prices = {}
    for t in tokens:
        prices[t] = await fetch_prices_for_token(session, t, exchanges)
    return prices

async def send_snapshot(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    cfg = CHAT_SETTINGS.get(chat_id, {})
    tokens = cfg.get("tokens", DEFAULT_TOKENS)
    exchanges = cfg.get("exchanges", DEFAULT_EXCHANGES)
    threshold = cfg.get("threshold", DEFAULT_THRESHOLD)
    async with aiohttp.ClientSession() as session:
        prices = await fetch_all_prices(session, tokens, exchanges)
    spreads = compute_spreads(prices)
    text = format_markdown(prices, spreads, threshold)
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    CHAT_SETTINGS.setdefault(chat_id, {
        "tokens": DEFAULT_TOKENS,
        "threshold": DEFAULT_THRESHOLD,
        "interval": DEFAULT_INTERVAL,
        "exchanges": DEFAULT_EXCHANGES,
    })
    cfg = CHAT_SETTINGS[chat_id]
    # schedule periodic job
    interval = cfg["interval"]
    # cancel previous jobs for this chat
    for job in context.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()
    context.job_queue.run_repeating(send_snapshot, interval=interval, chat_id=chat_id, name=str(chat_id), first=1)
    await update.message.reply_text(
        f"Бот запущен. Интервал обновления: {interval}s, порог: {cfg['threshold']}%, токены: {', '.join(cfg['tokens'])}.\n"
        f"Команды: /once, /set_threshold, /set_interval, /set_tokens, /set_exchanges, /status, /stop"
    )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    for job in context.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()
    await update.message.reply_text("Окей, автообновления остановлены. Используй /start для возобновления или /once для разового снимка.")

async def once(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # one-off snapshot now
    chat_id = update.effective_chat.id
    cfg = CHAT_SETTINGS.setdefault(chat_id, {
        "tokens": DEFAULT_TOKENS,
        "threshold": DEFAULT_THRESHOLD,
        "interval": DEFAULT_INTERVAL,
        "exchanges": DEFAULT_EXCHANGES,
    })
    # Send snapshot
    job_context = type("obj", (), {"job": type("obj", (), {"chat_id": chat_id})})()
    await send_snapshot(context=type("ctx", (), {"job": job_context, "bot": context.bot})())

async def set_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        val = float(context.args[0])
    except Exception:
        await update.message.reply_text("Использование: /set_threshold 0.5  (в процентах)")
        return
    CHAT_SETTINGS.setdefault(chat_id, {})["threshold"] = val
    await update.message.reply_text(f"Порог установлен на {val}%")

async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        sec = int(context.args[0])
    except Exception:
        await update.message.reply_text("Использование: /set_interval 60  (в секундах)")
        return
    CHAT_SETTINGS.setdefault(chat_id, {})["interval"] = sec
    await update.message.reply_text(f"Интервал обновления установлен на {sec} сек. Перезапусти /start чтобы применить.")

async def set_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Использование: /set_tokens BTC,ETH,SOL,BNB")
        return
    tokens = [t.strip().upper() for t in " ".join(context.args).split(",") if t.strip()]
    CHAT_SETTINGS.setdefault(chat_id, {})["tokens"] = tokens
    await update.message.reply_text(f"Токены установлены: {', '.join(tokens)}")

async def set_exchanges(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Использование: /set_exchanges binance,coinbase,kraken,kucoin,bybit,okx,bitstamp")
        return
    exchanges = [e.strip().lower() for e in " ".join(context.args).split(",") if e.strip()]
    CHAT_SETTINGS.setdefault(chat_id, {})["exchanges"] = exchanges
    await update.message.reply_text(f"Биржи установлены: {', '.join(exchanges)}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cfg = CHAT_SETTINGS.get(chat_id, {})
    await update.message.reply_text(
        f"Текущие настройки:\n"
        f"- tokens: {', '.join(cfg.get('tokens', []))}\n"
        f"- exchanges: {', '.join(cfg.get('exchanges', []))}\n"
        f"- threshold: {cfg.get('threshold', 0)}%\n"
        f"- interval: {cfg.get('interval', 0)} сек."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/start — запустить автообновления\n"
        "/stop — остановить автообновления\n"
        "/once — прислать разовый снимок цен\n"
        "/set_threshold <pct> — установить порог спреда в %\n"
        "/set_interval <sec> — интервал автообновления в секундах\n"
        "/set_tokens BTC,ETH,SOL,BNB — токены для мониторинга\n"
        "/set_exchanges binance,coinbase,... — список бирж\n"
        "/status — показать текущие настройки"
    )

def main():
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не найден. Укажите его в .env")
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("once", once))
    app.add_handler(CommandHandler("set_threshold", set_threshold))
    app.add_handler(CommandHandler("set_interval", set_interval))
    app.add_handler(CommandHandler("set_tokens", set_tokens))
    app.add_handler(CommandHandler("set_exchanges", set_exchanges))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_cmd))
    # JobQueue starts automatically
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
