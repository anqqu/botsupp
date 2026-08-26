import asyncpg
from config import DATABASE_URL

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(DATABASE_URL)
        await self.init_tables()

    async def init_tables(self):
        async with self.pool.acquire() as conn:
            # Таблицы из bot.py
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tickets (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    thread_id BIGINT,
                    last_message_id BIGINT,
                    ticket_number INTEGER,
                    status INTEGER,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id BIGINT PRIMARY KEY,
                    username TEXT
                );
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS message_map (
                    support_msg_id BIGINT PRIMARY KEY,
                    user_id        BIGINT NOT NULL,
                    user_msg_id    BIGINT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_topic_messages (
                    topic_msg_id BIGINT PRIMARY KEY,
                    user_id      BIGINT NOT NULL
                );
            ''')
            # Таблицы из ban.py
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS blocked_users (
                    user_id BIGINT PRIMARY KEY,
                    reason TEXT,
                    blocked_at TEXT,
                    notified INTEGER DEFAULT 0,
                    last_notified_at TEXT
                );
                CREATE TABLE IF NOT EXISTS appeals (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    created_at TEXT,
                    status TEXT DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS ban_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    username TEXT,
                    admin_id BIGINT,
                    admin_username TEXT,
                    reason TEXT,
                    banned_at TEXT,
                    action TEXT
                );
                CREATE TABLE IF NOT EXISTS appeal_thread (
                    id INTEGER PRIMARY KEY,
                    thread_id BIGINT
                );
            ''')
            # Аналог INSERT OR IGNORE для PostgreSQL
            await conn.execute('''
                INSERT INTO appeal_thread (id) VALUES (1) 
                ON CONFLICT (id) DO NOTHING;
            ''')

    # --- Универсальные методы ---

    async def execute(self, query: str, *args):
        """Для INSERT, UPDATE, DELETE (не возвращает строки)"""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args):
        """Для SELECT, который возвращает несколько строк (fetchall)"""
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        """Для SELECT, который возвращает одну строку (fetchone)"""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        """Для SELECT, который возвращает одно конкретное значение"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

# Создаем глобальный объект, который будем импортировать в другие файлы
db = Database()