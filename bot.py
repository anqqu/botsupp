import os
import random
import asyncio
import json
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InputMediaPhoto, InputMediaVideo, MessageEntity, BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from aiogram.exceptions import TelegramBadRequest
# устаревшие переменные
from config import BOT_TOKEN, SUPPORT_GROUP_ID
from database import db

# Настройка логирования
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler()  # Для вывода в консоль при тестировании
    ]
)
logger = logging.getLogger(__name__)


# Инициализация бота, роутера и диспетчера
bot = Bot(token=BOT_TOKEN)
router = Router()
dp = Dispatcher()


# Временное хранилище для альбомов
media_groups = {}

async def export_tickets():
    """Выгрузка тикетов в JSON."""
    rows = await db.fetch("SELECT user_id, username, ticket_number, status, created_at FROM tickets")
    tickets = [
        {
            "user_id": row["user_id"],
            "username": row["username"],
            "ticket_number": row["ticket_number"],
            "status": "open" if row["status"] else "closed",
            "created_at": row["created_at"]
        } for row in rows
    ]
    with open("tickets.json", "w", encoding="utf-8") as f:
        json.dump(tickets, f, ensure_ascii=False, indent=2)

async def create_new_topic(user_id: int, username: str) -> int:
    """Создаёт новую тему в группе поддержки и сохраняет её id в базе."""
    topic = await bot.create_forum_topic(
        chat_id=SUPPORT_GROUP_ID,
        name=f"@{username}"
    )
    thread_id = topic.message_thread_id
    await db.execute("UPDATE tickets SET thread_id = $1 WHERE user_id = $2", thread_id, user_id)
    return thread_id

async def create_or_get_thread(user_id: int, username: str, ticket_number: int = None) -> int:
    """Возвращает id существующей темы или создаёт новую.
    Тема не проверяется на актуальность здесь — это делается в момент
    непосредственной отправки реального сообщения пользователя
    (см. process_single_message / process_media_group)."""
    thread_id = await db.fetchval("SELECT thread_id FROM tickets WHERE user_id = $1", user_id)
    if thread_id:
        return thread_id
    return await create_new_topic(user_id, username)

@router.message(CommandStart())
async def start(message: Message):
    """Обработчик команды /start."""
    await message.reply("Привет! Напиши свой вопрос, и я помогу.")

@router.message(Command("help"))
async def help_command(message: Message):
    """Команда /help для отображения списка доступных команд."""
    if message.chat.type == "private":
        help_text = (
            "Список доступных команд:\n"
            "/start - Начать общение с ботом\n"
            "/help - Показать список команд"
        )
        await message.reply(help_text)
    elif message.chat.id == SUPPORT_GROUP_ID:
        help_text = (
            "Список доступных команд:\n\n"
            "📩 <b>Тикеты</b>\n"
            "/close — Закрыть тикет (в топике)\n"
            "/delete — Удалить сообщение у пользователя (reply)\n\n"
            "📝 <b>Шаблоны</b>\n"
            "/t название — Отправить шаблон пользователю\n"
            "/tcreate название — Создать новый шаблон\n"
            "/tlist — Список всех шаблонов\n"
            "/tdelete название — Удалить шаблон\n\n"
            "👥 <b>Агенты</b>\n"
            "/addagent @username — Добавить агента\n"
            "/removeagent @username — Удалить агента\n"
            "/listagents — Список агентов\n\n"
            "🛡️ <b>Модерация</b>\n"
            "/ban причина — Заблокировать (reply)\n"
            "/unban — Разблокировать (reply или user_id)\n"
            "/banlist — Список заблокированных\n"
            "/banhistory — История блокировок\n\n"
            "/export — Экспорт тикетов в JSON\n"
            "/help — Показать этот список"
        )
        await message.reply(help_text, parse_mode="HTML")

@router.message(Command("addagent"), F.chat.type.in_({"group", "supergroup"}))
async def add_agent(message: Message):
    """Команда /addagent @username или /addagent user_id."""
    if message.chat.id != SUPPORT_GROUP_ID:
        await message.reply("Эта команда доступна только в группе поддержки.")
        return
    # Проверяем, что отправитель — администратор группы
    admins = await bot.get_chat_administrators(SUPPORT_GROUP_ID)
    if message.from_user.id not in [admin.user.id for admin in admins]:
        await message.reply("Эта команда доступна только администраторам группы.")
        return
    
    # Проверяем аргументы команды
    if len(message.text.split()) < 2:
        await message.reply("Используйте: /addagent @username или /addagent user_id")
        return
    
    arg = message.text.split()[1]
    user_id = None
    username = None
    
    # Проверяем, является ли аргумент числовым user_id
    if arg.isdigit():
        user_id = int(arg)
    else:
        # Проверяем, является ли аргумент упоминанием (@username)
        entities = message.entities or []
        user_mention = None
        for entity in entities:
            if entity.type == "mention":
                user_mention = entity
                break
        if not user_mention:
            await message.reply("Используйте: /addagent @username или /addagent user_id (упомяните пользователя через @ или укажите числовой ID)")
            return
        # Извлекаем юзернейм и user_id из упоминания
        username = message.text[user_mention.offset + 1:user_mention.offset + user_mention.length]
        if user_mention.user:
            user_id = user_mention.user.id
        else:
            await message.reply("Не удалось определить user_id. Упомяните пользователя через @ и убедитесь, что бот может видеть его.")
            return
    
    # Проверяем, есть ли пользователь в группе
    try:
        member = await bot.get_chat_member(SUPPORT_GROUP_ID, user_id)
        # Проверяем статус участника (должен быть member, administrator или creator)
        if member.status not in ["member", "administrator", "creator"]:
            await message.reply(f"Пользователь с ID {user_id} не является активным участником группы (статус: {member.status}).")
            return
        # Если username не указан (например, при использовании user_id), пытаемся его получить
        if not username:
            username = member.user.username or f"User{user_id}"
        await db.execute(
            "INSERT INTO agents (agent_id, username) VALUES ($1, $2) ON CONFLICT (agent_id) DO NOTHING",
            user_id, username
        )
        await message.reply(f"Агент @{username} (ID: {user_id}) добавлен.")
        
    except TelegramBadRequest:
        await message.reply(f"Пользователь с ID {user_id} не найден в группе.")

@router.message(Command("removeagent"), F.chat.type.in_({"group", "supergroup"}))
async def remove_agent(message: Message):
    """Команда /removeagent @username."""
    if message.chat.id != SUPPORT_GROUP_ID:
        await message.reply("Эта команда доступна только в группе поддержки.")
        return
    # Проверяем, что отправитель — администратор группы
    admins = await bot.get_chat_administrators(SUPPORT_GROUP_ID)
    if message.from_user.id not in [admin.user.id for admin in admins]:
        await message.reply("Эта команда доступна только администраторам группы.")
        return
    if len(message.text.split()) < 2 or not message.text.startswith("/removeagent @"):
        await message.reply("Используйте: /removeagent @username")
        return
    username = message.text.split()[1]
    if not username.startswith("@"):
        await message.reply("Укажите юзернейм с @, например: /removeagent @username")
        return
    username = username[1:]  # Убираем @
    result = await db.execute("DELETE FROM agents WHERE username = $1", username)
    deleted = int(result.split()[-1]) if result else 0
    if deleted > 0:
        await message.reply(f"Агент @{username} удалён.")
    else:
        await message.reply(f"Агент @{username} не найден.")
    

@router.message(Command("listagents"), F.chat.type.in_({"group", "supergroup"}))
async def list_agents(message: Message):
    """Команда /listagents."""
    if message.chat.id != SUPPORT_GROUP_ID:
        await message.reply("Эта команда доступна только в группе поддержки.")
        return
    rows = await db.fetch("SELECT username FROM agents")
    agents = [row["username"] for row in rows]
    if agents:
        await message.reply("Агенты:\n" + "\n".join(f"@{agent}" for agent in agents))
    else:
        await message.reply("Агентов нет.")
    

@router.message(Command("export"), F.chat.type.in_({"group", "supergroup"}))
async def export_command(message: Message):
    """Команда /export для выгрузки тикетов."""
    if message.chat.id != SUPPORT_GROUP_ID:
        await message.reply("Эта команда доступна только в группе поддержки.")
        return
    await export_tickets()
    await message.reply("Тикеты выгружены в tickets.json.")
    await bot.send_document(
        chat_id=SUPPORT_GROUP_ID,
        document=types.FSInputFile("tickets.json"),
        caption="Экспорт тикетов"
    )

@router.message(Command("close"), F.chat.type.in_({"group", "supergroup"}))
async def close(message: Message):
    """Обработчик команды /close в группе поддержки."""
    if message.chat.id != SUPPORT_GROUP_ID:
        await message.reply("Эта команда доступна только в группе поддержки.")
        return

    if not message.message_thread_id:
        await message.reply("Используйте /close внутри топика тикета.")
        return

    row = await db.fetchrow(
        "SELECT user_id FROM tickets WHERE thread_id = $1 AND status = 1",
        message.message_thread_id
    )
    if not row:
        await message.reply("Активный тикет в этом топике не найден.")
        return

    user_id = row["user_id"]
    await db.execute("UPDATE tickets SET status = 0 WHERE user_id = $1", user_id)
    await bot.send_message(
        chat_id=SUPPORT_GROUP_ID,
        message_thread_id=message.message_thread_id,
        text="Вопрос закрыт."
    )
    await bot.send_message(
        chat_id=user_id,
        text="Вопрос решен. Напиши снова, если нужна помощь."
    )

@router.message(F.chat.type == "private")
async def handle_user_message(message: Message):
    """Обработчик сообщений от пользователей в личке."""
    user_id = message.from_user.id
    username = message.from_user.username or f"User{user_id}"
    media_group_id = message.media_group_id

    # --- проверка на бан ---
    row = await db.fetchrow("SELECT reason, last_notified_at FROM blocked_users WHERE user_id=$1", user_id)
    if row:
        reason, last_notified_at = row["reason"], row["last_notified_at"]
        current_date = datetime.now().strftime("%Y-%m-%d")
        should_notify = True

        if last_notified_at:
            last_notified_date = last_notified_at.split(" ")[0]  # Извлекаем только дату (YYYY-MM-DD)
            if last_notified_date == current_date:
                should_notify = False  # Уведомление уже отправлено сегодня

        if should_notify:
            # Отправляем уведомление без reply
            await message.answer(
                f"🚫 Вы были заблокированы.\n"
                f"Причина: {reason}\n\n"
                f"Если считаете блокировку ошибочной — используйте /appeal для подачи апелляции."
            )
            # Обновляем дату последнего уведомления
            await db.execute(
                "UPDATE blocked_users SET last_notified_at=$1 WHERE user_id=$2",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id
            )

        return
    # ------------------------

    # Проверяем, есть ли пользователь в базе
    ticket = await db.fetchrow(
        "SELECT thread_id, last_message_id, ticket_number, status FROM tickets WHERE user_id = $1", user_id
    )

    # Обработка альбомов
    if media_group_id:
        if media_group_id not in media_groups:
            media_groups[media_group_id] = []
        media_groups[media_group_id].append(message)
        # Ждём 0.5 секунды для сбора всех сообщений альбома
        await asyncio.sleep(0.5)
        if not media_groups.get(media_group_id):  # Пропускаем, если альбом уже обработан
            return
        messages = media_groups.pop(media_group_id)
        is_new_ticket = not ticket or not ticket["status"]
        ticket_number = random.randint(100000, 999999) if is_new_ticket else ticket["ticket_number"]
        await process_media_group(messages, user_id, username, ticket, ticket_number)
        if is_new_ticket:
            await message.reply("Сообщение доставлено, ждите ответа.")
            await notify_agents(user_id, username, ticket_number)
    else:
        # Обработка одиночного сообщения
        is_new_ticket = not ticket or not ticket["status"]
        ticket_number = random.randint(100000, 999999) if is_new_ticket else ticket["ticket_number"]
        await process_single_message(message, user_id, username, ticket, ticket_number)
        if is_new_ticket:
            await message.reply("Сообщение доставлено, ждите ответа.")
            await notify_agents(user_id, username, ticket_number)

async def process_single_message(message: Message, user_id: int, username: str, ticket, ticket_number: int):
    """Обработка одиночного сообщения."""
    chat_id = message.chat.id
    message_id = message.message_id
    media_description = "Сообщение"
    if message.text:
        media_description = message.text
    elif message.photo:
        media_description = "[Фото]" + (f" {message.caption}" if message.caption else "")
    elif message.video:
        media_description = "[Видео]" + (f" {message.caption}" if message.caption else "")
    elif message.document:
        media_description = "[Документ]" + (f" {message.caption}" if message.caption else "")
    elif message.sticker:
        media_description = "[Стикер]"
    elif message.audio:
        media_description = "[Аудио]"
    elif message.voice:
        media_description = "[Голосовое сообщение]"

    if not ticket:
        # Новый тикет — создаём тему
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        thread_id = await create_or_get_thread(user_id, username, ticket_number)
        try:
            support_message = await bot.forward_message(
                chat_id=SUPPORT_GROUP_ID,
                from_chat_id=chat_id,
                message_id=message_id,
                message_thread_id=thread_id
            )
        except TelegramBadRequest as e:
            if "message thread not found" in str(e).lower():
                thread_id = await create_new_topic(user_id, username)
                support_message = await bot.forward_message(
                    chat_id=SUPPORT_GROUP_ID,
                    from_chat_id=chat_id,
                    message_id=message_id,
                    message_thread_id=thread_id
                )
            elif "message can't be forwarded" in str(e).lower():
                support_message = await copy_single_media(message, username, thread_id)
            else:
                raise e
        await db.execute(
            "INSERT INTO tickets (user_id, username, thread_id, last_message_id, ticket_number, status, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            user_id, username, thread_id, support_message.message_id, ticket_number, 1, created_at
        )
        # Трекаем сообщение пользователя в топике
        await db.execute(
            "INSERT INTO user_topic_messages (topic_msg_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            support_message.message_id, user_id
        )
        return support_message.message_id
    else:
        # Существующий тикет — отправляем в тему
        thread_id = ticket["thread_id"]
        last_message_id = ticket["last_message_id"]
        status = ticket["status"]
        thread_id = await create_or_get_thread(user_id, username, ticket_number)  # Проверяем или создаём тему
        if not status:
            # Переоткрываем тикет
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await bot.send_message(
                chat_id=SUPPORT_GROUP_ID,
                message_thread_id=thread_id,
                text=f"Новый тикет #{ticket_number}"
            )
            await db.execute(
                "UPDATE tickets SET ticket_number = $1, status = 1, created_at = $2 WHERE user_id = $3",
                ticket_number, created_at, user_id
            )
        try:
            support_message = await bot.forward_message(
                chat_id=SUPPORT_GROUP_ID,
                from_chat_id=chat_id,
                message_id=message_id,
                message_thread_id=thread_id
            )
        except TelegramBadRequest as e:
            if "message thread not found" in str(e).lower():
                thread_id = await create_new_topic(user_id, username)
                support_message = await bot.forward_message(
                    chat_id=SUPPORT_GROUP_ID,
                    from_chat_id=chat_id,
                    message_id=message_id,
                    message_thread_id=thread_id
                )
            elif "message can't be forwarded" in str(e).lower():
                support_message = await copy_single_media(message, username, thread_id)
            else:
                raise e
        await db.execute(
            "UPDATE tickets SET last_message_id = $1 WHERE user_id = $2",
            support_message.message_id, user_id
        )
        # Трекаем сообщение пользователя в топике
        await db.execute(
            "INSERT INTO user_topic_messages (topic_msg_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            support_message.message_id, user_id
        )
        return support_message.message_id

async def process_media_group(messages: list, user_id: int, username: str, ticket, ticket_number: int):
    """Обработка альбома медиа."""
    chat_id = messages[0].chat.id
    media_count = len(messages)
    media_type = "фото" if messages[0].photo else "видео"
    caption = messages[0].caption or ""
    media_description = f"[Альбом: {media_count} {media_type}] {caption}"

    if not ticket:
        # Новый тикет — создаём тему
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        thread_id = await create_or_get_thread(user_id, username, ticket_number)
        try:
            support_message = await bot.forward_message(
                chat_id=SUPPORT_GROUP_ID,
                from_chat_id=chat_id,
                message_id=messages[0].message_id,
                message_thread_id=thread_id
            )
            first_message_id = support_message.message_id
        except TelegramBadRequest as e:
            if "message thread not found" in str(e).lower():
                thread_id = await create_new_topic(user_id, username)
                support_message = await bot.forward_message(
                    chat_id=SUPPORT_GROUP_ID,
                    from_chat_id=chat_id,
                    message_id=messages[0].message_id,
                    message_thread_id=thread_id
                )
                first_message_id = support_message.message_id
            elif "message can't be forwarded" in str(e).lower():
                support_message = await copy_media_group(messages, username, thread_id)
                first_message_id = support_message[0].message_id
            else:
                raise e
        await db.execute(
            "INSERT INTO tickets (user_id, username, thread_id, last_message_id, ticket_number, status, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            user_id, username, thread_id, first_message_id, ticket_number, 1, created_at
        )
        # Трекаем сообщение пользователя в топике
        await db.execute(
            "INSERT INTO user_topic_messages (topic_msg_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            first_message_id, user_id
        )
        return first_message_id
    else:
        # Существующий тикет — отправляем в тему
        thread_id = ticket["thread_id"]
        last_message_id = ticket["last_message_id"]
        status = ticket["status"]
        thread_id = await create_or_get_thread(user_id, username, ticket_number)  # Проверяем или создаём тему
        if not status:
            # Новый тикет
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await bot.send_message(
                chat_id=SUPPORT_GROUP_ID,
                message_thread_id=thread_id,
                text=f"Новый тикет #{ticket_number}"
            )
            await db.execute(
                "UPDATE tickets SET ticket_number = $1, status = 1, created_at = $2 WHERE user_id = $3",
                ticket_number, created_at, user_id
            )
        try:
            support_message = await bot.forward_message(
                chat_id=SUPPORT_GROUP_ID,
                from_chat_id=chat_id,
                message_id=messages[0].message_id,
                message_thread_id=thread_id
            )
            first_message_id = support_message.message_id
        except TelegramBadRequest as e:
            if "message thread not found" in str(e).lower():
                thread_id = await create_new_topic(user_id, username)
                support_message = await bot.forward_message(
                    chat_id=SUPPORT_GROUP_ID,
                    from_chat_id=chat_id,
                    message_id=messages[0].message_id,
                    message_thread_id=thread_id
                )
                first_message_id = support_message.message_id
            elif "message can't be forwarded" in str(e).lower():
                support_message = await copy_media_group(messages, username, thread_id)
                first_message_id = support_message[0].message_id
            else:
                raise e
        await db.execute(
            "UPDATE tickets SET last_message_id = $1 WHERE user_id = $2",
            first_message_id, user_id
        )
        # Трекаем сообщение пользователя в топике
        await db.execute(
            "INSERT INTO user_topic_messages (topic_msg_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            first_message_id, user_id
        )
        return first_message_id

async def copy_single_media(message: Message, username: str, thread_id: int = None):
    """Копирование одиночного медиа."""
    caption = f"@{username}: "
    if message.text:
        caption += message.text
        return await bot.send_message(
            chat_id=SUPPORT_GROUP_ID,
            message_thread_id=thread_id,
            text=caption,
        )
    elif message.photo:
        caption += "[Фото]" + (f" {message.caption}" if message.caption else "")
        return await bot.send_photo(
            chat_id=SUPPORT_GROUP_ID,
            message_thread_id=thread_id,
            photo=message.photo[-1].file_id,
            caption=caption,
        )
    elif message.video:
        caption += "[Видео]" + (f" {message.caption}" if message.caption else "")
        return await bot.send_video(
            chat_id=SUPPORT_GROUP_ID,
            message_thread_id=thread_id,
            video=message.video.file_id,
            caption=caption,
        )
    elif message.document:
        caption += "[Документ]" + (f" {message.caption}" if message.caption else "")
        return await bot.send_document(
            chat_id=SUPPORT_GROUP_ID,
            message_thread_id=thread_id,
            document=message.document.file_id,
            caption=caption,
        )
    elif message.sticker:
        caption += "[Стикер]"
        return await bot.send_message(
            chat_id=SUPPORT_GROUP_ID,
            message_thread_id=thread_id,
            text=caption,
        )
    elif message.audio:
        caption += "[Аудио]" + (f" {message.caption}" if message.caption else "")
        return await bot.send_audio(
            chat_id=SUPPORT_GROUP_ID,
            message_thread_id=thread_id,
            audio=message.audio.file_id,
            caption=caption,
        )
    elif message.voice:
        caption += "[Голосовое сообщение]"
        return await bot.send_voice(
            chat_id=SUPPORT_GROUP_ID,
            message_thread_id=thread_id,
            voice=message.voice.file_id,
            caption=caption,
        )

async def copy_media_group(messages: list, username: str, thread_id: int = None):
    """Копирование альбома медиа."""
    media_group = []
    media_count = len(messages)
    media_type = "фото" if messages[0].photo else "видео"
    caption = f"@{username}: [Альбом: {media_count} {media_type}] {messages[0].caption or ''}"
    for msg in messages:
        if msg.photo:
            media_group.append(InputMediaPhoto(media=msg.photo[-1].file_id, caption=caption if not media_group else None))
        elif msg.video:
            media_group.append(InputMediaVideo(media=msg.video.file_id, caption=caption if not media_group else None))
    return await bot.send_media_group(
        chat_id=SUPPORT_GROUP_ID,
        message_thread_id=thread_id,
        media=media_group,
    )

async def notify_agents(user_id: int, username: str, ticket_number: int):
    """Уведомление агентов о новом тикете."""
    rows = await db.fetch("SELECT agent_id FROM agents")
    for row in rows:
        await bot.send_message(
            chat_id=row["agent_id"],
            text=f"Новый тикет #{ticket_number} от @{username}"
        )

@router.message(F.chat.type.in_({"group", "supergroup"}), ~F.text.startswith("/"))
async def handle_support_message(message: Message):
    if message.chat.id != SUPPORT_GROUP_ID:
        return

    if message.from_user and message.from_user.is_bot:
        return

    # Игнорируем сообщения вне топиков (общий чат группы)
    if not message.message_thread_id:
        return

    # Только reply на сообщение пользователя пересылается пользователю.
    # Свободные сообщения — внутреннее обсуждение.
    # Проверяем через БД: если replied-to message — сообщение пользователя,
    # то reply_to_message есть и его message_id есть в user_topic_messages.
    if not message.reply_to_message:
        return

    user_row = await db.fetchrow(
        "SELECT user_id FROM user_topic_messages WHERE topic_msg_id = $1",
        message.reply_to_message.message_id
    )
    if not user_row:
        return  # reply на внутреннее сообщение команды, не пересылаем

    user_id = user_row["user_id"]

    # Проверяем что тикет ещё открыт
    is_open = await db.fetchval(
        "SELECT status FROM tickets WHERE user_id = $1",
        user_id
    )
    if not is_open:
        await message.reply("⚠️ Тикет закрыт. Используйте /close для подтверждения закрытия.")
        return

    # Обновляем last_message_id (для обратной трассировки)
    await db.execute(
        "UPDATE tickets SET last_message_id = $1 WHERE user_id = $2",
        message.message_id, user_id
    )

    # Обработка медиа-группы (альбома)
    if message.media_group_id:
        if message.media_group_id not in media_groups:
            media_groups[message.media_group_id] = []
        media_groups[message.media_group_id].append(message)
        # Ждём 0.5 секунды для сбора всех сообщений альбома
        await asyncio.sleep(0.5)
        messages = media_groups.pop(message.media_group_id, None)
        if not messages:
            return
        sent_list = await send_media_group_to_user(messages, user_id)
        # Сохраняем маппинг первого сообщения альбома
        if sent_list:
            await db.execute(
                "INSERT INTO message_map (support_msg_id, user_id, user_msg_id) "
                "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                messages[0].message_id, user_id, sent_list[0].message_id
            )
    else:
        # Обработка одиночного сообщения
        sent = await send_single_message_to_user(message, user_id)
        if sent:
            await db.execute(
                "INSERT INTO message_map (support_msg_id, user_id, user_msg_id) "
                "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                message.message_id, user_id, sent.message_id
            )



async def send_single_message_to_user(message: Message, user_id: int):
    """Отправка одиночного сообщения пользователю. Возвращает объект отправленного сообщения."""
    try:
        if message.text:
            return await bot.send_message(
                chat_id=user_id,
                text=message.text
            )
        elif message.photo:
            return await bot.send_photo(
                chat_id=user_id,
                photo=message.photo[-1].file_id,
                caption=message.caption if message.caption else None
            )
        elif message.video:
            return await bot.send_video(
                chat_id=user_id,
                video=message.video.file_id,
                caption=message.caption if message.caption else None
            )
        elif message.document:
            return await bot.send_document(
                chat_id=user_id,
                document=message.document.file_id,
                caption=message.caption if message.caption else None
            )
        elif message.sticker:
            return await bot.send_sticker(
                chat_id=user_id,
                sticker=message.sticker.file_id
            )
        elif message.audio:
            return await bot.send_audio(
                chat_id=user_id,
                audio=message.audio.file_id,
                caption=message.caption if message.caption else None
            )
        elif message.voice:
            return await bot.send_voice(
                chat_id=user_id,
                voice=message.voice.file_id,
                caption=message.caption if message.caption else None
            )
        else:
            return await bot.send_message(
                chat_id=user_id,
                text="Извините, этот тип сообщения не поддерживается."
            )
    except Exception as e:
        logger.error(f"Ошибка при отправке одиночного сообщения пользователю {user_id}: {str(e)}")
        await bot.send_message(
            chat_id=SUPPORT_GROUP_ID,
            message_thread_id=message.message_thread_id,
            text=f"Ошибка при отправке сообщения пользователю {user_id}: {str(e)}"
        )
        return None

async def send_media_group_to_user(messages: list, user_id: int):
    """Отправка медиа-группы (альбома) пользователю. Возвращает список отправленных сообщений."""
    try:
        media_group = []
        for msg in messages:
            if msg.photo:
                media_group.append(InputMediaPhoto(
                    media=msg.photo[-1].file_id,
                    caption=msg.caption if msg.caption and not media_group else None
                ))
            elif msg.video:
                media_group.append(InputMediaVideo(
                    media=msg.video.file_id,
                    caption=msg.caption if msg.caption and not media_group else None
                ))
        if media_group:
            return await bot.send_media_group(
                chat_id=user_id,
                media=media_group
            )
        else:
            await bot.send_message(
                chat_id=user_id,
                text="Извините, этот альбом не поддерживается."
            )
            return None
    except Exception as e:
        logger.error(f"Ошибка при отправке медиа-группы пользователю {user_id}: {str(e)}")
        await bot.send_message(
            chat_id=SUPPORT_GROUP_ID,
            message_thread_id=messages[0].message_thread_id,
            text=f"Ошибка при отправке альбома пользователю {user_id}: {str(e)}"
        )
        return None


@router.message(Command("delete"), F.chat.type.in_({"group", "supergroup"}))
async def delete_user_message(message: Message):
    """Команда /delete — удаляет у пользователя сообщение, отправленное сапортом.
    Используется как reply на сообщение в топике."""
    if message.chat.id != SUPPORT_GROUP_ID:
        return
    if not message.reply_to_message:
        await message.reply(
            "Используйте /delete в ответ на сообщение в топике, "
            "которое хотите удалить у пользователя."
        )
        return

    support_msg_id = message.reply_to_message.message_id
    row = await db.fetchrow(
        "SELECT user_id, user_msg_id FROM message_map WHERE support_msg_id = $1",
        support_msg_id
    )
    if not row:
        await message.reply(
            "❌ Сообщение не найдено в базе.\n"
            "Возможно, оно было системным или бот перезапускался после его отправки."
        )
        return

    user_id = row["user_id"]
    user_msg_id = row["user_msg_id"]

    try:
        await bot.delete_message(chat_id=user_id, message_id=user_msg_id)
        await db.execute("DELETE FROM message_map WHERE support_msg_id = $1", support_msg_id)
        await message.reply("✅ Сообщение удалено у пользователя.")
    except TelegramBadRequest as e:
        if "message to delete not found" in str(e).lower():
            await message.reply("⚠️ Сообщение уже удалено пользователем или не найдено.")
            await db.execute("DELETE FROM message_map WHERE support_msg_id = $1", support_msg_id)
        else:
            await message.reply(f"❌ Ошибка при удалении: {e}")

async def main():
    """Запуск бота."""
    
    await db.connect()
    
    # Настройка команд для личных чатов
    await bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Начать общение с ботом"),
            BotCommand(command="appeal", description="Описать причину разблокировки"),
            BotCommand(command="help", description="Показать список команд")
        ],
        scope=BotCommandScopeDefault()
    )
    
    # Настройка команд для группы поддержки
    await bot.set_my_commands(
        commands=[
            BotCommand(command="close", description="Закрыть тикет (в топике)"),
            BotCommand(command="delete", description="Удалить сообщение у пользователя (reply)"),
            BotCommand(command="t", description="Отправить шаблон пользователю"),
            BotCommand(command="tcreate", description="Создать новый шаблон"),
            BotCommand(command="tlist", description="Список шаблонов"),
            BotCommand(command="tdelete", description="Удалить шаблон"),
            BotCommand(command="addagent", description="Добавить агента (@username или user_id)"),
            BotCommand(command="removeagent", description="Удалить агента (@username)"),
            BotCommand(command="listagents", description="Показать список агентов"),
            BotCommand(command="export", description="Экспортировать тикеты в JSON"),
            BotCommand(command="ban", description="Заблокировать пользователя"),
            BotCommand(command="unban", description="Разблокировать пользователя"),
            BotCommand(command="banlist", description="Список заблокированных"),
            BotCommand(command="banhistory", description="История блокировок"),
            BotCommand(command="help", description="Показать список команд")
        ],
        scope=BotCommandScopeChat(chat_id=SUPPORT_GROUP_ID)
    )

    import ban as ban_module
    import templates as templates_module

    dp.include_router(ban_module.router)
    dp.include_router(templates_module.router)  # До основного — для корректного приоритета FSM
    dp.include_router(router)

    logger.info("Бот запущен... Нажмите Ctrl+C для завершения.")

    try:
        await dp.start_polling(bot, skip_updates=True)
    except KeyboardInterrupt:
        logger.info("Остановка бота... (Ctrl+C)")
    finally:
        # Корректное завершение работы
        if db.pool:
            await db.pool.close()  # Закрываем пул соединений PostgreSQL
        await bot.session.close()  # Закрываем сессию Telegram
        logger.info("Бот завершил работу.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановка бота завершена.")
    except Exception as e:
        logger.error(f"Произошла ошибка: {e}")
