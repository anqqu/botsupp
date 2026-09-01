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
from aiogram.utils.text_decorations import html_decoration

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


# Доступные эффекты сообщений
EFFECTS = {
    "fireworks": ("5046509860389126442", "🎉 Фейерверк"),
    "heart":     ("5159385139981059251", "❤️ Сердечко"),
    "fire":      ("5104841245755180586", "🔥 Огонь"),
}


class TemplateForm(StatesGroup):
    waiting_for_content = State()
    waiting_for_effect  = State()


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
@router.message(Command("cancel"), TemplateForm.waiting_for_effect)
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
        # html_text сохраняет ссылки, жирный, курсив и прочее форматирование
        content = message.html_text
    elif message.photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
        # html_decoration.unparse применяет caption entities -> HTML
        content = html_decoration.unparse(
            message.caption or "",
            message.caption_entities or []
        )
    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
        content = html_decoration.unparse(
            message.caption or "",
            message.caption_entities or []
        )
    elif message.document:
        content_type = "document"
        file_id = message.document.file_id
        content = html_decoration.unparse(
            message.caption or "",
            message.caption_entities or []
        )
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

    # Сохраняем данные в state — запись в БД после выбора эффекта
    await state.update_data(
        content_type=content_type,
        content=content,
        file_id=file_id,
        created_at=created_at,
    )
    await state.set_state(TemplateForm.waiting_for_effect)

    # Строим пикер эффектов
    effect_buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"teffect:{key}")
         for key, (_, label) in EFFECTS.items()],
        [InlineKeyboardButton(text="⏭️ Без эффекта", callback_data="teffect:none")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="teffect_cancel")],
    ]
    emoji = CONTENT_TYPE_EMOJI.get(content_type, "📝")
    await message.reply(
        f"{emoji} Контент получен! Выберите эффект для шаблона <b>«{name}»</b>:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=effect_buttons)
    )


# ──────────────────────────────────────────────────────────────
#  Callback: teffect:<key>  — выбор эффекта и сохранение шаблона
# ──────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("teffect:"), TemplateForm.waiting_for_effect)
async def callback_teffect(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 1)[1]
    data = await state.get_data()

    name        = data["template_name"]
    content_type = data["content_type"]
    content     = data.get("content")
    file_id     = data.get("file_id")
    creator_id  = data.get("creator_id")
    created_at  = data["created_at"]

    # Определяем effect_id
    effect_id = None
    effect_label = "Без эффекта"
    if key != "none" and key in EFFECTS:
        effect_id, effect_label = EFFECTS[key]

    await db.execute(
        "INSERT INTO templates (name, content_type, content, file_id, created_by, created_at, effect_id) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        name, content_type, content, file_id, creator_id, created_at, effect_id
    )
    await state.clear()
    await call.answer()

    # Удаляем пикер и показываем подтверждение
    emoji = CONTENT_TYPE_EMOJI.get(content_type, "📝")
    effect_hint = f" · {effect_label}" if effect_id else ""
    await call.message.edit_text(
        f"✅ Шаблон {emoji} <b>«{name}»</b> создан{effect_hint}!\n"
        f"Использование: <code>/t {name}</code>",
        parse_mode="HTML"
    )
    logger.info(f"Template '{name}' created with effect_id={effect_id} by {creator_id}")


# ──────────────────────────────────────────────────────────────
#  Callback: teffect_cancel  — отмена создания на этапе эффекта
# ──────────────────────────────────────────────────────────────
@router.callback_query(F.data == "teffect_cancel", TemplateForm.waiting_for_effect)
async def callback_teffect_cancel(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data.get("template_name", "")
    await state.clear()
    await call.answer("Отменено.")
    await call.message.edit_text(f"❌ Создание шаблона «{name}» отменено.")


# ──────────────────────────────────────────────────────────────
#  Используется и из /t, и из callback tsend:
# ──────────────────────────────────────────────────────────────
async def _send_template_to_user(
    bot: Bot,
    row: dict,
    user_id: int,
    support_msg_id: int,
    reply_chat_id: int,
    reply_msg_id: int,
    thread_id: int | None,
) -> str:
    """
    Отправляет шаблон пользователю, сохраняет message_map для /delete.
    Возвращает HTML-текст подтверждения (без медиа).
    """
    ct = row["content_type"]
    caption = row["content"] or None
    name = row["name"]
    effect_id: str | None = row.get("effect_id") or None

    async def _do_send(with_effect: bool) -> object:
        eid = effect_id if with_effect else None
        if ct == "text":
            return await bot.send_message(
                chat_id=user_id, text=row["content"],
                parse_mode="HTML",
                message_effect_id=eid
            )
        elif ct == "photo":
            return await bot.send_photo(
                chat_id=user_id, photo=row["file_id"],
                caption=caption or None, parse_mode="HTML",
                message_effect_id=eid
            )
        elif ct == "video":
            return await bot.send_video(
                chat_id=user_id, video=row["file_id"],
                caption=caption or None, parse_mode="HTML",
                message_effect_id=eid
            )
        elif ct == "document":
            return await bot.send_document(
                chat_id=user_id, document=row["file_id"],
                caption=caption or None, parse_mode="HTML",
                message_effect_id=eid
            )
        elif ct == "voice":
            return await bot.send_voice(
                chat_id=user_id, voice=row["file_id"],
                message_effect_id=eid
            )
        elif ct == "sticker":
            return await bot.send_sticker(chat_id=user_id, sticker=row["file_id"])
        else:
            raise ValueError(f"Неизвестный content_type: {ct}")

    # Пробуем с эффектом; если Telegram отклонил — повторяем без него
    try:
        sent = await _do_send(with_effect=True)
    except Exception as e:
        if effect_id and "EFFECT_ID_INVALID" in str(e):
            logger.warning(f"Effect {effect_id} rejected by Telegram, sending without effect")
            sent = await _do_send(with_effect=False)
        else:
            raise

    # Маппинг для /delete
    await db.execute(
        "INSERT INTO message_map (support_msg_id, user_id, user_msg_id) "
        "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
        support_msg_id, user_id, sent.message_id
    )

    emoji = CONTENT_TYPE_EMOJI.get(ct, "📝")
    confirm_header = f"✅ Шаблон {emoji} <b>«{name}»</b> отправлен пользователю."

    # Подтверждение с превью
    if ct == "text":
        await bot.send_message(
            chat_id=reply_chat_id,
            text=f"{confirm_header}\n\n<blockquote>{row['content']}</blockquote>",
            parse_mode="HTML",
            message_thread_id=thread_id,
            reply_to_message_id=reply_msg_id
        )
    elif ct in ("photo", "video", "document", "voice"):
        send_fn = {
            "photo": bot.send_photo,
            "video": bot.send_video,
            "document": bot.send_document,
            "voice": bot.send_voice,
        }[ct]
        file_kwarg = {
            "photo": "photo", "video": "video",
            "document": "document", "voice": "voice"
        }[ct]
        extra_caption = (f"\n<blockquote>{caption}</blockquote>" if caption and ct != "voice" else "")
        await send_fn(
            chat_id=reply_chat_id,
            **{file_kwarg: row["file_id"]},
            caption=confirm_header + extra_caption,
            parse_mode="HTML",
            message_thread_id=thread_id,
            reply_to_message_id=reply_msg_id
        )
    else:
        await bot.send_message(
            chat_id=reply_chat_id,
            text=confirm_header,
            parse_mode="HTML",
            message_thread_id=thread_id,
            reply_to_message_id=reply_msg_id
        )

    return confirm_header


def _build_template_picker(rows, callback_prefix: str) -> InlineKeyboardMarkup:
    """Строит клавиатуру выбора шаблона: 2 кнопки в ряд + кнопка Отмена."""
    buttons = []
    row_buf = []
    for r in rows:
        emoji = CONTENT_TYPE_EMOJI.get(r["content_type"], "📝")
        btn = InlineKeyboardButton(
            text=f"{emoji} {r['name']}",
            callback_data=f"{callback_prefix}:{r['name']}"
        )
        row_buf.append(btn)
        if len(row_buf) == 2:
            buttons.append(row_buf)
            row_buf = []
    if row_buf:
        buttons.append(row_buf)
    # Кнопка отмены отдельной строкой
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="tcancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ──────────────────────────────────────────────────────────────
#  /t [название]  — отправить шаблон или показать пикер
# ──────────────────────────────────────────────────────────────
@router.message(Command("t"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_use_template(message: Message, bot: Bot):
    if message.chat.id != SUPPORT_GROUP_ID:
        return
    if not message.message_thread_id:
        await message.reply("⚠️ Эта команда используется только внутри топика тикета.")
        return

    # Проверяем тикет заранее (нужен и для пикера, и для прямой отправки)
    ticket = await db.fetchrow(
        "SELECT user_id, status FROM tickets WHERE thread_id = $1",
        message.message_thread_id
    )
    if not ticket:
        await message.reply("❌ Этот топик не связан ни с одним тикетом.")
        return
    if not ticket["status"]:
        await message.reply("⚠️ Тикет закрыт. Нельзя отправить шаблон.")
        return

    parts = message.text.split(maxsplit=1)
    name = parts[1].strip().lower().replace(" ", "_") if len(parts) >= 2 and parts[1].strip() else None

    # ── Режим пикера: /t без аргумента ──
    if not name:
        rows = await db.fetch("SELECT name, content_type FROM templates ORDER BY name")
        if not rows:
            await message.reply(
                "📋 Шаблонов пока нет.\n"
                "Создайте первый: <code>/tcreate название</code>",
                parse_mode="HTML"
            )
            return

        keyboard = _build_template_picker(rows, callback_prefix="tsend")
        await message.reply(
            "📝 <b>Выберите шаблон для отправки:</b>",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    # ── Режим прямой отправки: /t rules ──
    row = await db.fetchrow("SELECT * FROM templates WHERE name = $1", name)
    if not row:
        await message.reply(
            f"❌ Шаблон <b>«{name}»</b> не найден.\n"
            f"Список шаблонов: <code>/tlist</code>",
            parse_mode="HTML"
        )
        return

    try:
        await _send_template_to_user(
            bot=bot, row=dict(row),
            user_id=ticket["user_id"],
            support_msg_id=message.message_id,
            reply_chat_id=message.chat.id,
            reply_msg_id=message.message_id,
            thread_id=message.message_thread_id,
        )
        logger.info(f"Template '{name}' sent to user {ticket['user_id']} by {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error sending template '{name}': {e}")
        await message.reply(f"❌ Ошибка при отправке шаблона: {e}")


# ──────────────────────────────────────────────────────────────
#  Callback: tsend:<name>  — выбор из пикера → отправить
# ──────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("tsend:"))
async def callback_tsend(call: CallbackQuery, bot: Bot):
    if call.message.chat.id != SUPPORT_GROUP_ID:
        await call.answer()
        return

    name = call.data.split(":", 1)[1]
    thread_id = call.message.message_thread_id

    # Ищем тикет по топику
    ticket = await db.fetchrow(
        "SELECT user_id, status FROM tickets WHERE thread_id = $1", thread_id
    )
    if not ticket:
        await call.answer("❌ Топик не связан с тикетом.", show_alert=True)
        return
    if not ticket["status"]:
        await call.answer("⚠️ Тикет закрыт.", show_alert=True)
        return

    row = await db.fetchrow("SELECT * FROM templates WHERE name = $1", name)
    if not row:
        await call.answer(f"Шаблон «{name}» не найден.", show_alert=True)
        return

    await call.answer()  # убираем часики

    try:
        await _send_template_to_user(
            bot=bot, row=dict(row),
            user_id=ticket["user_id"],
            support_msg_id=call.message.message_id,
            reply_chat_id=call.message.chat.id,
            reply_msg_id=call.message.message_id,
            thread_id=thread_id,
        )
        # Удаляем пикер
        await call.message.delete()
        logger.info(f"Template '{name}' sent via picker to user {ticket['user_id']} by {call.from_user.id}")
    except Exception as e:
        logger.error(f"Error sending template '{name}' via picker: {e}")
        await call.message.answer(f"❌ Ошибка при отправке шаблона: {e}")


# ──────────────────────────────────────────────────────────────
#  Callback: tcancel  — закрыть пикер
# ──────────────────────────────────────────────────────────────
@router.callback_query(F.data == "tcancel")
async def callback_tcancel(call: CallbackQuery):
    await call.answer("Отменено.")
    await call.message.delete()



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
