import aiosqlite
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                rating REAL NOT NULL DEFAULT 5.0,
                rating_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                kind TEXT NOT NULL,
                game TEXT NOT NULL,
                description TEXT NOT NULL,
                contact TEXT NOT NULL,
                payment TEXT NOT NULL,
                price REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                published_message_id INTEGER,
                media_json TEXT NOT NULL DEFAULT '[]'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.commit()