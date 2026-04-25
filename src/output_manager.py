from telegram.ext import CallbackContext

from mode_enum import Mode
from telegram import Update

__mode: Mode | None = None
__context: CallbackContext | None = None


def init_output_manager(mode: Mode):
    global __mode
    __mode = mode


def set_update_context(context: CallbackContext):
    global __context
    __context = context


async def _print(text: str):
    if __mode == Mode.CLI:
        print(text)
    elif __mode == Mode.TELEGRAM:
        if __context is None:
            print(text)
            print("⚠️ Telegram context not provided.")
            return

        chat_id = getattr(__context, "_chat_id", None)

        if chat_id is None:
            print("⚠️ Cannot determine chat_id from context.")
            return

        await __context.bot.send_message(
            chat_id=chat_id, text=text, parse_mode="Markdown"
        )
