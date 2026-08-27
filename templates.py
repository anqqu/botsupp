"""
Модуль шаблонов быстрых ответов для группы поддержки.

Команды:
  /tcreate <название> — интерактивное создание шаблона
  /t <название>       — отправить шаблон пользователю в текущем тикете
  /tlist              — список всех шаблонов
  /tdelete <название> — удалить шаблон
"""

import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import SUPPORT_GROUP_ID
from database import db

logger = logging.getLogger(__name__)
router = Router()

CONTENT_TYPE_EMOJI = {
    "text":     "📝",
    "photo":    "🖼️",
    "video":    "🎥",
    "document": "📄",
    "voice":    "🎤",
    "sticker":  "🎭",
}


class TemplateForm(StatesGroup):
    waiting_for_content = State()


# ──────────────────────────────────────────────────────────────
#  /tcreate <название>  — начало создания шаблона
# ──────────────────────────────────────────────────────────────
@router.message(Command("tcreate"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_tcreate(message: Message, state: FSMContext):
    if message.chat.id != SUPPORT_GROUP_ID:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            "❌ Укажите название шаблона.\n"
            "Пример: <code>/tcreate rules</code>",
            parse_mode="HTML"
        )
        return

    name = parts[1].strip().lower().replace(" ", "_")

    # Проверяем существование
    existing = await db.fetchrow("SELECT name FROM templates WHERE name = $1", name)
    if existing:
        await message.reply(
            f"⚠️ Шаблон <b>«{name}»</b> уже существует.\n"
            f"Удалите его командой <code>/tdelete {name}</code> и создайте заново.",
            parse_mode="HTML"
        )
        return

    await state.set_state(TemplateForm.waiting_for_content)
    await state.update_data(template_name=name, creator_id=message.from_user.id)

    await message.reply(
        f"📝 <b>Создание шаблона «{name}»</b>\n\n"
        "Отправьте сообщение, которое станет шаблоном.\n"
        "Поддерживаются: текст, фото, видео, документ, голосовое, стикер.\n\n"
        "Для отмены: <code>/cancel</code>",
        parse_mode="HTML"
    )


# ──────────────────────────────────────────────────────────────
#  /cancel — отмена создания шаблона
# ──────────────────────────────────────────────────────────────
@router.message(Command("cancel"), TemplateForm.waiting_for_content)
async def cmd_cancel(message: Message, state: FSMContext):
    data = await state.get_data()
    name = data.get("template_name", "")
    await state.clear()
    await message.reply(f"❌ Создание шаблона «{name}» отменено.")


# ──────────────────────────────────────────────────────────────
#  Обработка контента шаблона (состояние ожидания сообщения)
# ──────────────────────────────────────────────────────────────
@router.message(TemplateForm.waiting_for_content, F.chat.type.in_({"group", "supergroup"}))
async def save_template_content(message: Message, state: FSMContext):
    if message.chat.id != SUPPORT_GROUP_ID:
        return

    data = await state.get_data()
    name = data["template_name"]
    creator_id = data.get("creator_id")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content_type = None
    content = None
    file_id = None

    if message.text:
        content_type = "text"
        content = message.text
    elif message.photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
        content = message.caption or ""
    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
        content = message.caption or ""
    elif message.document:
        content_type = "document"
        file_id = message.document.file_id
        content = message.caption or ""
    elif message.voice:
        content_type = "voice"
        file_id = message.voice.file_id
        content = ""
    elif message.sticker:
        content_type = "sticker"
        file_id = message.sticker.file_id
        content = ""
    else:
        await message.reply(
            "❌ Неподдерживаемый тип сообщения.\n"
            "Используйте: текст, фото, видео, документ, голосовое или стикер."
        )
        return

    await db.execute(
        "INSERT INTO templates (name, content_type, content, file_id, created_by, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        name, content_type, content, file_id, creator_id, created_at
    )
    await state.clear()

    emoji = CONTENT_TYPE_EMOJI.get(content_type, "📝")
    await message.reply(
        f"✅ Шаблон {emoji} <b>«{name}»</b> успешно создан!\n"
        f"Использование: <code>/t {name}</code>",
        parse_mode="HTML"
    )


# ──────────────────────────────────────────────────────────────
#  /t <название>  — отправить шаблон пользователю в топике
# ──────────────────────────────────────────────────────────────
@router.message(Command("t"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_use_template(message: Message, bot: Bot):
    if message.chat.id != SUPPORT_GROUP_ID:
        return
    if not message.message_thread_id:
        await message.reply("⚠️ Эта команда используется только внутри топика тикета.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            "❌ Укажите название шаблона.\n"
            "Пример: <code>/t rules</code>\n"
            "Список шаблонов: <code>/tlist</code>",
            parse_mode="HTML"
        )
        return

    name = parts[1].strip().lower().replace(" ", "_")

    # Ищем шаблон
    row = await db.fetchrow("SELECT * FROM templates WHERE name = $1", name)
    if not row:
        await message.reply(
            f"❌ Шаблон <b>«{name}»</b> не найден.\n"
            f"Список шаблонов: <code>/tlist</code>",
            parse_mode="HTML"
        )
        return

    # Находим пользователя по топику
    ticket = await db.fetchrow(
        "SELECT user_id, status FROM tickets WHERE thread_id = $1",
        message.message_thread_id
    )
    if not ticket:
        await message.reply("❌ Этот топик не связан ни с одним тикетом.")
        return
    if not ticket["status"]:
        await message.reply("⚠️ Тикет закрыт. Нельзя отправить шаблон в закрытый тикет.")
        return

    user_id = ticket["user_id"]

    # Отправляем шаблон пользователю
    try:
        ct = row["content_type"]
        caption = row["content"] or None

        if ct == "text":
            sent = await bot.send_message(chat_id=user_id, text=row["content"])
        elif ct == "photo":
            sent = await bot.send_photo(chat_id=user_id, photo=row["file_id"], caption=caption)
        elif ct == "video":
            sent = await bot.send_video(chat_id=user_id, video=row["file_id"], caption=caption)
        elif ct == "document":
            sent = await bot.send_document(chat_id=user_id, document=row["file_id"], caption=caption)
        elif ct == "voice":
            sent = await bot.send_voice(chat_id=user_id, voice=row["file_id"])
        elif ct == "sticker":
            sent = await bot.send_sticker(chat_id=user_id, sticker=row["file_id"])
        else:
            await message.reply(f"❌ Неизвестный тип шаблона: {ct}")
            return

        # Сохраняем маппинг для /delete
        await db.execute(
            "INSERT INTO message_map (support_msg_id, user_id, user_msg_id) "
            "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            message.message_id, user_id, sent.message_id
        )

        emoji = CONTENT_TYPE_EMOJI.get(ct, "📝")
        await message.reply(
            f"✅ Шаблон {emoji} <b>«{name}»</b> отправлен пользователю.",
            parse_mode="HTML"
        )
        logger.info(f"Template '{name}' sent to user {user_id} by {message.from_user.id}")

    except Exception as e:
        logger.error(f"Error sending template '{name}' to user {user_id}: {e}")
        await message.reply(f"❌ Ошибка при отправке шаблона: {e}")


# ──────────────────────────────────────────────────────────────
#  /tlist  — список всех шаблонов с кнопками превью
# ──────────────────────────────────────────────────────────────
@router.message(Command("tlist"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_tlist(message: Message):
    if message.chat.id != SUPPORT_GROUP_ID:
        return

    rows = await db.fetch("SELECT name, content_type FROM templates ORDER BY name")
    if not rows:
        await message.reply(
            "📋 Шаблонов пока нет.\n"
            "Создайте первый: <code>/tcreate название</code>",
            parse_mode="HTML"
        )
        return

    # Строим инлайн-клавиатуру: по 2 кнопки в ряд
    buttons = []
    row_buf = []
    for r in rows:
        emoji = CONTENT_TYPE_EMOJI.get(r["content_type"], "📝")
        btn = InlineKeyboardButton(
            text=f"{emoji} {r['name']}",
            callback_data=f"tpreview:{r['name']}"
        )
        row_buf.append(btn)
        if len(row_buf) == 2:
            buttons.append(row_buf)
            row_buf = []
    if row_buf:
        buttons.append(row_buf)

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.reply(
        f"📋 <b>Список шаблонов</b> — нажмите для просмотра:\n"
        f"<i>Всего: {len(rows)}</i>",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# ──────────────────────────────────────────────────────────────
#  Callback: превью шаблона
# ──────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("tpreview:"))
async def callback_tpreview(call: CallbackQuery, bot: Bot):
    if call.message.chat.id != SUPPORT_GROUP_ID:
        await call.answer()
        return

    name = call.data.split(":", 1)[1]
    row = await db.fetchrow("SELECT * FROM templates WHERE name = $1", name)
    if not row:
        await call.answer(f"Шаблон «{name}» не найден.", show_alert=True)
        return

    await call.answer()  # закрываем «часики» на кнопке

    ct = row["content_type"]
    emoji = CONTENT_TYPE_EMOJI.get(ct, "📝")
    header = f"{emoji} <b>Шаблон «{name}»</b> — превью:"
    caption = row["content"] or ""

    try:
        if ct == "text":
            await call.message.answer(
                f"{header}\n\n{row['content']}",
                parse_mode="HTML"
            )
        elif ct == "photo":
            await bot.send_photo(
                chat_id=call.message.chat.id,
                photo=row["file_id"],
                caption=f"{header}\n{caption}" if caption else header,
                parse_mode="HTML",
                message_thread_id=call.message.message_thread_id
            )
        elif ct == "video":
            await bot.send_video(
                chat_id=call.message.chat.id,
                video=row["file_id"],
                caption=f"{header}\n{caption}" if caption else header,
                parse_mode="HTML",
                message_thread_id=call.message.message_thread_id
            )
        elif ct == "document":
            await bot.send_document(
                chat_id=call.message.chat.id,
                document=row["file_id"],
                caption=f"{header}\n{caption}" if caption else header,
                parse_mode="HTML",
                message_thread_id=call.message.message_thread_id
            )
        elif ct == "voice":
            await bot.send_voice(
                chat_id=call.message.chat.id,
                voice=row["file_id"],
                caption=header,
                parse_mode="HTML",
                message_thread_id=call.message.message_thread_id
            )
        elif ct == "sticker":
            await call.message.answer(
                f"{header}\n<i>(стикеры нельзя предпросматривать как медиа)</i>",
                parse_mode="HTML"
            )
    except Exception as e:
        await call.message.answer(f"❌ Ошибка при превью шаблона «{name}»: {e}")


# ──────────────────────────────────────────────────────────────
#  /tdelete <название>  — удалить шаблон
# ──────────────────────────────────────────────────────────────
@router.message(Command("tdelete"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_tdelete(message: Message):
    if message.chat.id != SUPPORT_GROUP_ID:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            "❌ Укажите название шаблона.\n"
            "Пример: <code>/tdelete rules</code>",
            parse_mode="HTML"
        )
        return

    name = parts[1].strip().lower().replace(" ", "_")
    result = await db.execute("DELETE FROM templates WHERE name = $1", name)

    # asyncpg возвращает "DELETE N" где N — кол-во удалённых строк
    deleted_count = int(result.split()[-1]) if result else 0

    if deleted_count:
        await message.reply(f"🗑️ Шаблон <b>«{name}»</b> удалён.", parse_mode="HTML")
    else:
        await message.reply(
            f"❌ Шаблон <b>«{name}»</b> не найден.\n"
            f"Список шаблонов: <code>/tlist</code>",
            parse_mode="HTML"
        )
