<div align="center">

# 🎫 Telegram Support Bot

**Мощный бот технической поддержки с тикет-системой, форумами топиков и модерацией.**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Aiogram](https://img.shields.io/badge/Aiogram-3.x-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![AsyncPG](https://img.shields.io/badge/asyncpg-ready-2b5b84?style=for-the-badge)](https://github.com/MagicStack/asyncpg)

</div>

---

## 🌟 Основные возможности

* **🧵 Топики под каждого пользователя:** Бот автоматически создает и ведет отдельную форум-тему (Topic) в группе поддержки для каждого клиента.
* **🔒 Внутренний командный чат:** Обычные сообщения команды в топике **не видны** пользователю (идеально для внутреннего обсуждения). Чтобы ответить клиенту — достаточно сделать **Reply** на его сообщение.
* **🗑️ Удаление сообщений у клиента:** Ошиблись в ответе? Команда `/delete` (в ответ на сообщение саппорта) удалит отправленное сообщение прямо из переписки с пользователем.
* **🛡️ Полноценная модерация и баны:**
  * Блокировка и разблокировка пользователей с указанием причин.
  * Пагинация и поиск по списку заблокированных (`/banlist`).
  * Полная история блокировок и действий модераторов (`/banhistory`).
* **📨 Система апелляций:** Заблокированные пользователи могут подать заявку на разбан через `/appeal`, а администраторы — одобрить или отклонить её прямо кнопками в общем топике апелляций.
* **👥 Управление агентами:** Уведомления дежурных агентов о новых тикетах (`/addagent`, `/listagents`).
* **📁 Поддержка медиа:** Корректная обработка и пересылка одиночных медиа, альбомов (media groups), документов, голосовых и стикеров.
* **💾 Экспорт данных:** Быстрая выгрузка истории тикетов в формат JSON (`/export`).

---

## 🛠️ Стек технологий

| Компонент | Технология | Назначение |
| :--- | :--- | :--- |
| **Backend** | Python 3.12 / Aiogram 3.x | Асинхронный фреймворк для Telegram Bot API |
| **Database** | PostgreSQL 16 | Надежное реляционное хранилище данных |
| **DB Driver** | asyncpg | Высокопроизводительный асинхронный пул соединений |
| **Deployment** | Docker & Docker Compose | Контейнеризация и автоматический запуск |

---

## 🚀 Быстрый старт

### 1. Клонирование репозитория

```bash
git clone https://github.com/anqqu/botsupp.git
cd botsupp
```

### 2. Настройка переменных окружения

Создайте файл `.env` из примера:

```bash
cp .env.example .env
nano .env
```

Заполните ваши данные:

```ini
# Telegram Bot
BOT_TOKEN=xxx:xxx
SUPPORT_GROUP_ID=-100xxx

# PostgreSQL
POSTGRES_USER=bot_user
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=support_db
```

> **Важно:** Группа поддержки должна быть супергруппой с включенным режимом **Тем (Topics / Forum Mode)**, а бот должен иметь права администратора.

### 3. Запуск через Docker Compose

```bash
# Сборка и фоновый запуск
docker compose up -d --build
```

### 4. Полезные команды управления

```bash
# Просмотр логов в реальном времени
docker compose logs -f bot

# Остановка бота
docker compose down

# Перезапуск бота
docker compose restart bot

# Остановка с полной очисткой базы данных (осторожно!)
docker compose down -v
```

---

## 📖 Справочник команд

### 🛠️ Команды в группе поддержки

| Команда | Описание |
| :--- | :--- |
| `/close` | Закрыть текущий тикет (вызывается внутри топика) |
| `/delete` | Удалить сообщение у пользователя (в ответ на сообщение саппорта) |
| `/ban <причина>` | Заблокировать пользователя (в ответ на сообщение) |
| `/unban [id]` | Разблокировать пользователя (по reply или указав user_id) |
| `/banlist [стр/ник]` | Интерактивный список забаненных с пагинацией и поиском |
| `/banhistory <@user/id>` | Просмотр истории банов и действий модераторов |
| `/addagent <@user/id>` | Назначить агента для получения уведомлений |
| `/removeagent @user` | Удалить агента из списка рассылки |
| `/listagents` | Показать список назначенных агентов |
| `/export` | Выгрузить файл `tickets.json` со всеми тикетами |
| `/help` | Показать справку по командам |

### 👤 Команды для пользователей (в ЛС)

| Команда | Описание |
| :--- | :--- |
| `/start` | Начать диалог с поддержкой / создать обращение |
| `/appeal` | Подать апелляцию на разблокировку (доступно забаненным раз в 7 дней) |
| `/help` | Справка по использованию |

---

## 📁 Структура проекта

```text
botsupp/
├── bot.py               # Основная логика тикетов, роутинг сообщений и альбомов
├── ban.py               # Модуль модерации: баны, история, апелляции
├── database.py          # Инициализация таблиц PostgreSQL и обертка asyncpg
├── config.py            # Загрузка и валидация конфигурации
├── Dockerfile           # Описание сборки контейнера бота
├── docker-compose.yml   # Оркестрация контейнеров бота и PostgreSQL
├── requirements.txt     # Python-зависимости
├── .env.example         # Шаблон файла конфигурации
└── .dockerignore        # Исключения файлов для Docker
```

---

<div align="center">
Made with ❤️ for efficient customer support
</div>
