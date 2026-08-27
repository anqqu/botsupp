from datetime import datetime, timedelta
from aiogram import Router, Bot, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import SUPPORT_GROUP_ID
from database import db


router = Router()


# --- /ban ---
@router.message(Command("ban"), F.chat.type.in_({"group", "supergroup"}))
async def ban_user(message: types.Message, bot: Bot):
    if message.chat.id != SUPPORT_GROUP_ID:
        return
    admins = await bot.get_chat_administrators(SUPPORT_GROUP_ID)
    if message.from_user.id not in [admin.user.id for admin in admins]:
        await message.reply("Команда доступна только администраторам.")
        return
    if not message.reply_to_message:
        await message.reply("Используйте: /ban <причина> (в ответ на сообщение пользователя)")
        return

    reason = message.text.replace("/ban", "").strip() or "Причина не указана"

    row = await db.fetchrow(
        "SELECT user_id, username FROM tickets WHERE last_message_id=$1",
        message.reply_to_message.message_id
    )
    if not row:
        thread_id = getattr(message.reply_to_message, "message_thread_id", None)
        if thread_id:
            row = await db.fetchrow(
                "SELECT user_id, username FROM tickets WHERE thread_id=$1", thread_id
            )
    if not row:
        await message.reply("Не удалось определить пользователя.")
        return

    user_id, username = row
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # добавляем в список банов (аналог INSERT OR REPLACE)
    await db.execute(
        "INSERT INTO blocked_users (user_id, reason, blocked_at, notified) VALUES ($1, $2, $3, 0) "
        "ON CONFLICT (user_id) DO UPDATE SET reason = EXCLUDED.reason, blocked_at = EXCLUDED.blocked_at, "
        "notified = 0, last_notified_at = NULL",
        user_id, reason, now_str
    )
    # история
    await db.execute(
        "INSERT INTO ban_history (user_id, username, admin_id, admin_username, reason, banned_at, action) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        user_id, username, message.from_user.id, message.from_user.username, reason, now_str, "ban"
    )

    await message.reply(f"Пользователь {user_id} заблокирован. Причина: {reason}")

    # Пытаемся уведомить пользователя о бане сразу
    try:
        await bot.send_message(
            user_id,
            f"🚫 Вы были заблокированы.\n"
            f"Причина: {reason}\n\n"
            f"Если считаете блокировку ошибочной — используйте /appeal для подачи апелляции."
        )
        # Обновляем дату последнего уведомления
        await db.execute(
            "UPDATE blocked_users SET last_notified_at=$1 WHERE user_id=$2",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id
        )
    except Exception as e:
        print(f"Не удалось отправить уведомление пользователю {user_id}: {e}")


# --- /unban ---
@router.message(Command("unban"), F.chat.type.in_({"group", "supergroup"}))
async def unban_user(message: types.Message, bot: Bot):
    if message.chat.id != SUPPORT_GROUP_ID:
        return
    admins = await bot.get_chat_administrators(SUPPORT_GROUP_ID)
    if message.from_user.id not in [admin.user.id for admin in admins]:
        await message.reply("Команда доступна только администраторам.")
        return

    user_id = None
    username = None
    if message.reply_to_message:
        row = await db.fetchrow(
            "SELECT user_id, username FROM tickets WHERE last_message_id=$1",
            message.reply_to_message.message_id
        )
        if not row:
            thread_id = getattr(message.reply_to_message, "message_thread_id", None)
            if thread_id:
                row = await db.fetchrow(
                    "SELECT user_id, username FROM tickets WHERE thread_id=$1", thread_id
                )
        if row:
            user_id, username = row
    else:
        args = message.text.split()
        if len(args) > 1 and args[1].isdigit():
            user_id = int(args[1])

    if not user_id:
        await message.reply("Использование: /unban (в ответ на сообщение) или /unban user_id")
        return

    result = await db.execute("DELETE FROM blocked_users WHERE user_id=$1", user_id)
    affected = int(result.split()[-1]) if result else 0
    if affected:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            "INSERT INTO ban_history (user_id, username, admin_id, admin_username, reason, banned_at, action) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            user_id, username, message.from_user.id, message.from_user.username, "Разбан", now_str, "unban"
        )

    if affected:
        await message.reply(f"Пользователь {user_id} разблокирован.")
        try:
            await bot.send_message(user_id, "✅ Вы были разблокированы и можете снова обращаться в поддержку.")
        except:
            pass
    else:
        await message.reply("Пользователь не найден в списке заблокированных.")


# --- /banlist ---
@router.message(Command("banlist"), F.chat.type.in_({"group", "supergroup"}))
async def banlist(message: types.Message):
    args = message.text.split()
    page = 1
    search_username = None
    if len(args) > 1:
        if args[1].isdigit():
            page = int(args[1])
        else:
            search_username = args[1].lstrip("@")

    text, total_pages = await get_banlist_page(page, search_username)
    kb = make_banlist_keyboard(page, total_pages, search_username) if message.chat.id == SUPPORT_GROUP_ID else None
    await message.reply(text, reply_markup=kb)


@router.callback_query(F.data.startswith("banlist:"))
async def banlist_callback(call: CallbackQuery):
    if call.message.chat.id != SUPPORT_GROUP_ID:
        return
    _, page_str, search = call.data.split(":", 2)
    page = int(page_str)
    search_username = search if search else None
    text, total_pages = await get_banlist_page(page, search_username)
    kb = make_banlist_keyboard(page, total_pages, search_username)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


async def get_banlist_page(page: int, search_username: "str | None"):
    limit = 10
    offset = (page - 1) * limit
    if search_username:
        rows = await db.fetch(
            """SELECT b.user_id, t.username, b.reason, b.blocked_at
               FROM blocked_users b
               LEFT JOIN tickets t ON b.user_id = t.user_id
               WHERE t.username LIKE $1
               ORDER BY b.blocked_at DESC
               LIMIT $2 OFFSET $3""",
            f"%{search_username}%", limit, offset
        )
        total = await db.fetchval(
            """SELECT COUNT(*) FROM blocked_users b
               LEFT JOIN tickets t ON b.user_id = t.user_id
               WHERE t.username LIKE $1""",
            f"%{search_username}%"
        )
    else:
        rows = await db.fetch(
            """SELECT b.user_id, t.username, b.reason, b.blocked_at
               FROM blocked_users b
               LEFT JOIN tickets t ON b.user_id = t.user_id
               ORDER BY b.blocked_at DESC
               LIMIT $1 OFFSET $2""",
            limit, offset
        )
        total = await db.fetchval("SELECT COUNT(*) FROM blocked_users")
    total_pages = (total + limit - 1) // limit if total else 1
    if not rows:
        return "Список заблокированных пуст.", total_pages
    text = f"📋 Заблокированные (стр. {page}/{total_pages})"
    if search_username:
        text += f" | поиск: @{search_username}"
    text += ":\n\n"
    for row in rows:
        uid, uname, reason, when = row
        uname_disp = f"@{uname}" if uname else "—"
        text += f"🔒 {uname_disp} | id:{uid} | {when.split()[0]} | {reason}\n"
    return text[:4000], total_pages


def make_banlist_keyboard(page: int, total_pages: int, search_username: "str | None"):
    kb = InlineKeyboardBuilder()
    search = search_username or ""
    if page > 1:
        kb.button(text="⬅️ Назад", callback_data=f"banlist:{page-1}:{search}")
    if page < total_pages:
        kb.button(text="➡️ Вперёд", callback_data=f"banlist:{page+1}:{search}")
    return kb.as_markup() if kb.buttons else None


# --- /banhistory ---
@router.message(Command("banhistory"), F.chat.type.in_({"group", "supergroup"}))
async def banhistory(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply("Использование: /banhistory @username или /banhistory user_id")
        return
    search = args[1].lstrip("@")
    if search.isdigit():
        rows = await db.fetch(
            """SELECT user_id, username, admin_username, reason, banned_at, action
               FROM ban_history WHERE user_id=$1 ORDER BY banned_at DESC""",
            int(search)
        )
    else:
        rows = await db.fetch(
            """SELECT user_id, username, admin_username, reason, banned_at, action
               FROM ban_history WHERE username LIKE $1 ORDER BY banned_at DESC""",
            f"%{search}%"
        )
    if not rows:
        await message.reply("История пуста.")
        return
    text = f"📜 История блокировок для {search}:\n\n"
    for uid, uname, admin, reason, when, action in rows[:20]:
        text += f"{when} | {action.upper()} | id:{uid} (@{uname or '—'}) | мод: @{admin or '—'} | {reason}\n"
    await message.reply(text[:4000])


# --- /appeal (только ЛС пользователя) ---
@router.message(Command("appeal"), F.chat.type == "private")
async def appeal(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    row = await db.fetchrow("SELECT reason FROM blocked_users WHERE user_id=$1", user_id)
    if not row:
        await message.reply("Вы не заблокированы и можете писать напрямую.")
        return
    reason = row["reason"]
    last = await db.fetchrow(
        "SELECT created_at FROM appeals WHERE user_id=$1 ORDER BY created_at DESC LIMIT 1", user_id
    )
    if last:
        last_dt = datetime.strptime(last["created_at"], "%Y-%m-%d %H:%M:%S")
        if datetime.now() - last_dt < timedelta(days=7):
            await message.reply("Вы уже подавали апелляцию. Попробуйте снова через неделю.")
            return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    appeal_id = await db.fetchval(
        "INSERT INTO appeals (user_id, created_at) VALUES ($1, $2) RETURNING id",
        user_id, now_str
    )
    # Проверяем, есть ли ID общей темы апелляций в базе
    thread_id = await db.fetchval("SELECT thread_id FROM appeal_thread WHERE id=1")

    if not thread_id:
        # Если темы нет, создаём её и сохраняем ID
        topic = await bot.create_forum_topic(SUPPORT_GROUP_ID, name="📂 Апелляции")
        thread_id = topic.message_thread_id
        await db.execute("UPDATE appeal_thread SET thread_id=$1 WHERE id=1", thread_id)

    fwd_msg = await bot.forward_message(SUPPORT_GROUP_ID, message.chat.id, message.message_id, message_thread_id=thread_id)
    caption = (f"📨 Апелляция #{appeal_id}\n"
               f"От: @{message.from_user.username or '—'} (id:{user_id})\n"
               f"Причина бана: {reason}\n"
               f"Дата: {now_str}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"appeal:accept:{appeal_id}:{user_id}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"appeal:reject:{appeal_id}:{user_id}")]
    ])
    await bot.send_message(SUPPORT_GROUP_ID, text=caption, message_thread_id=thread_id,
                           reply_to_message_id=fwd_msg.message_id, reply_markup=kb)
    await message.reply("Ваша апелляция отправлена. Ответ придёт в течение недели.")


@router.callback_query(F.data.startswith("appeal:"))
async def handle_appeal_action(call: CallbackQuery, bot: Bot):
    if call.message.chat.id != SUPPORT_GROUP_ID:
        return
    action, appeal_id, user_id = call.data.split(":")[1:]
    appeal_id = int(appeal_id)
    user_id = int(user_id)
    if action == "accept":
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Пытаемся получить username из предыдущих записей в ban_history
        username = await db.fetchval(
            "SELECT username FROM ban_history WHERE user_id=$1 ORDER BY banned_at DESC LIMIT 1", user_id
        )
        # Если username не найден, пробуем взять из call.message
        if not username and call.message.reply_to_message and call.message.reply_to_message.from_user:
            username = call.message.reply_to_message.from_user.username
        await db.execute("DELETE FROM appeals WHERE user_id=$1", user_id)  # Удаляем все апелляции пользователя
        await db.execute("DELETE FROM blocked_users WHERE user_id=$1", user_id)  # Удаляем бан
        await db.execute(
            "INSERT INTO ban_history (user_id, username, admin_id, admin_username, reason, banned_at, action) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            user_id, username, call.from_user.id, call.from_user.username or "Admin",
            "Разбан через апелляцию", now_str, "unban"
        )
        await bot.send_message(user_id, "✅ Ваша апелляция принята, доступ восстановлен.")
        await call.message.edit_text(call.message.text + "\n\n✅ Апелляция принята.")
    elif action == "reject":
        await db.execute("UPDATE appeals SET status='rejected' WHERE id=$1", appeal_id)
        await bot.send_message(user_id, "❌ Ваша апелляция отклонена. Попробуйте снова через неделю.")
        await call.message.edit_text(call.message.text + "\n\n❌ Апелляция отклонена.")
    await call.answer()


