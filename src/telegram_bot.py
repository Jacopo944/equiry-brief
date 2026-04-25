import os
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)
from mode_enum import Mode
from core import build_report, TELEGRAM_TOKEN
from output_manager import set_update_context

# Conversation states
ASK_TICKER = 1

# Utility to split long messages to Telegram-friendly chunks
MAX_MSG = 4000


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi!\n\n"
        "Send me one or more stock tickers (e.g. `AAPL` or `AAPL, TSLA`).\n\n"
        "📰 I’ll fetch the latest news and reply with a short summary."
    )
    return ASK_TICKER


async def print_report(filename: Path, update: Update):
    # Send the report content as text chunks to the user (Telegram has ~4096 char limit)
    try:
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()

        # split into MAX_MSG-sized chunks without breaking words too aggressively
        i = 0
        length = len(content)
        while i < length:
            chunk = content[i : i + MAX_MSG]
            # try to avoid cutting in the middle of a line: prefer last newline within chunk
            if i + MAX_MSG < length:
                nl = chunk.rfind("\n")
                if nl > max(0, int(MAX_MSG * 0.6)):
                    # cut at a newline if it's reasonably far into the chunk
                    chunk = chunk[: nl + 1]
                    i += nl + 1
                else:
                    i += MAX_MSG
            else:
                i += MAX_MSG

            # send each chunk as a message
            try:
                await update.message.reply_text(
                    text=chunk, parse_mode="Markdown", disable_web_page_preview=True
                )
            except Exception:
                # If sending as text fails for any reason, break and proceed to send file
                break

    except Exception as e:
        # If reading/sending text fails, notify but continue to attempt sending file
        await update.message.reply_text(f"⚠️ Failed to send report text: {e}")


async def receive_symbols(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""

    tickers = [t.strip().upper() for t in user_text.replace(",", " ").split()]

    if not tickers:
        await update.message.reply_text("⚠️ No tickers detected. Please try again.")
        return ASK_TICKER

    filename = await build_report(Mode.TELEGRAM, tickers)

    await update.message.reply_text("✅ Done — your report is ready.")

    await print_report(filename, update)

    os.remove(filename)

    # # Finally, attempt to send the .md file as an attachment (best-effort)
    # try:
    #     await update.message.reply_document(document=open(filename, "rb"))
    # except Exception as e:
    #     await update.message.reply_text(f"❌ Failed to send the .md file: {e}")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


async def direct_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return None

    if context.user_data.get("is_busy"):
        return None

    context.user_data["is_busy"] = True

    try:
        set_update_context(context)

        text = update.message.text.strip()
        if not text:
            return None

        if len(text) <= 80:
            await receive_symbols(update, context)
        else:
            await update.message.reply_text("⚠️ Message too long for ticker processing.")
    finally:
        context.user_data["is_busy"] = False

    return await start(update, context)


if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Please set TELEGRAM_BOT_TOKEN in your environment")

    app = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), CommandHandler("ticker", start)],
        states={
            ASK_TICKER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, direct_message_handler)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)

    print("Starting Telegram bot...")
    app.run_polling()
