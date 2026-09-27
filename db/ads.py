import json
from datetime import datetime, timezone
import aiosqlite
from config import DB_PATH


async def create_ad(data, user_id: int, username: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO ads(
                user_id, username, kind, game, description,
                contact, payment, price, status, created_at, media_json
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                user_id,
                username or "",
                data["kind"],
                data["game"],
                data["description"],
                data["contact"],
                data["payment"],
                float(data["price"]),
                "pending",
                datetime.now(timezone.utc).isoformat(),
                json.dumps(data.get("media", []), ensure_ascii=False),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_ad(ad_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM ads WHERE id=?", (ad_id,))
        return await cur.fetchone()


async def set_status(ad_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE ads SET status=? WHERE id=?",
            (status, ad_id),
        )
        await db.commit()


async def set_published(ad_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE ads SET status='published', published_message_id=? WHERE id=?",
            (message_id, ad_id),
        )
        await db.commit()


async def update_ad_media(ad_id: int, media):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE ads SET media_json=? WHERE id=?",
            (json.dumps(media, ensure_ascii=False), ad_id),
        )
        await db.commit()


async def update_ad_price(ad_id: int, new_price: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE ads SET price=? WHERE id=?",
            (new_price, ad_id),
        )
        await db.commit()


async def get_published_ads(kind=None, search=None, limit=30):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        if kind and kind != "all":
            if search:
                pattern = f"%{search}%"
                cur = await db.execute(
                    """
                    SELECT * FROM ads
                    WHERE status='published' AND kind=?
                      AND (game LIKE ? OR description LIKE ?)
                    ORDER BY id DESC LIMIT ?
                    """,
                    (kind, pattern, pattern, limit),
                )
            else:
                cur = await db.execute(
                    """
                    SELECT * FROM ads
                    WHERE status='published' AND kind=?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (kind, limit),
                )
        else:
            if search:
                pattern = f"%{search}%"
                cur = await db.execute(
                    """
                    SELECT * FROM ads
                    WHERE status='published'
                      AND (game LIKE ? OR description LIKE ? OR username LIKE ?)
                    ORDER BY id DESC LIMIT ?
                    """,
                    (pattern, pattern, pattern, limit),
                )
            else:
                cur = await db.execute(
                    "SELECT * FROM ads WHERE status='published' ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
        return await cur.fetchall()


async def get_user_ads_count(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM ads WHERE user_id=?",
            (user_id,),
        )
        return (await cur.fetchone())[0]


async def get_user_ads(user_id: int, limit: int = 30):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, kind, game, price, status FROM ads
            WHERE user_id=? ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        )
        return await cur.fetchall()


async def get_recent_ads(limit: int = 30):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, kind, game, price, status FROM ads
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        return await cur.fetchall()