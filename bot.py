import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from html import escape
from io import BytesIO

import aiosqlite
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
)


# ============================================================
# НАСТРОЙКИ
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DATABASE_PATH", "market.db").strip()
PUBLIC_CHANNEL = os.getenv("PUBLIC_CHANNEL", "").strip()
PUBLIC_CHANNEL_URL = os.getenv("PUBLIC_CHANNEL_URL", "").strip()

try:
    ADMIN_IDS = {
        int(x.strip())
        for x in os.getenv("ADMIN_IDS", "").split(",")
        if x.strip()
    }
except ValueError:
    ADMIN_IDS = set()


if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не указан в .env"
    )


bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    ),
)

dp = Dispatcher()
router = Router()
dp.include_router(router)


# ============================================================
# СОСТОЯНИЯ
# ============================================================


class SellForm(StatesGroup):
    kind = State()
    game = State()
    description = State()
    media = State()
    contact = State()
    payment = State()
    price = State()


class BuySearch(StatesGroup):
    query = State()


class AdminRating(StatesGroup):
    user_id = State()
    rating = State()


class AdminWatermark(StatesGroup):
    photo = State()


class AdminReplacePhoto(StatesGroup):
    ad_id = State()


# ============================================================
# КОНСТАНТЫ
# ============================================================


KIND_NAMES = {
    "account": "Учётная запись",
    "currency": "Валюта",
    "service": "Услуга",
    "other": "Другое",
}


KIND_EMOJI = {
    "account": "🪪",
    "currency": "🪙",
    "service": "🛠",
    "other": "📦",
}


PAY_NAMES = {
    "card": "Перевод с карты на карту или через СБП",
    "stars": "Telegram Stars",
    "both": (
        "Перевод с карты на карту или через СБП "
        "или Telegram Stars"
    ),
}


STATUS_NAMES = {
    "pending": "⏳ На модерации",
    "published": "✅ Опубликовано",
    "rejected": "❌ Отклонено",
    "sold": "💰 Продано",
    "error": "⚠️ Ошибка",
}


# ============================================================
# КЛАВИАТУРЫ
# ============================================================


def main_menu(
    user_id: int | None = None,
) -> InlineKeyboardMarkup:

    rows = [
        [
            InlineKeyboardButton(
                text="🛍 Купить",
                callback_data="buy",
            )
        ],
        [
            InlineKeyboardButton(
                text="📦 Продать товар",
                callback_data="sell",
            )
        ],
        [
            InlineKeyboardButton(
                text="👤 Мой профиль",
                callback_data="profile",
            ),
            InlineKeyboardButton(
                text="📋 Мои объявления",
                callback_data="my_ads",
            ),
        ],
        [
            InlineKeyboardButton(
                text="ℹ️ Правила",
                callback_data="rules",
            ),
            InlineKeyboardButton(
                text="🆘 Поддержка",
                callback_data="support",
            ),
        ],
    ]

    if user_id in ADMIN_IDS:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⚙️ Админ-панель",
                    callback_data="admin_panel",
                )
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_sell",
                )
            ]
        ]
    )


def kind_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🪪 Аккаунт",
                    callback_data="kind:account",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🪙 Валюта",
                    callback_data="kind:currency",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛠 Услуга",
                    callback_data="kind:service",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Другое",
                    callback_data="kind:other",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_sell",
                )
            ],
        ]
    )


def payment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Карта / СБП",
                    callback_data="pay:card",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭐ Telegram Stars",
                    callback_data="pay:stars",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💳 + ⭐ Оба варианта",
                    callback_data="pay:both",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_sell",
                )
            ],
        ]
    )


def admin_kb(
    ad_id: int,
) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить",
                    callback_data=f"approve:{ad_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject:{ad_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🖼 Заменить главное фото",
                    callback_data=f"replace_photo:{ad_id}",
                )
            ],
        ]
    )


def buy_categories_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Все товары",
                    callback_data="buy:cat:all",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🪪 Аккаунты",
                    callback_data="buy:cat:account",
                ),
                InlineKeyboardButton(
                    text="🪙 Валюта",
                    callback_data="buy:cat:currency",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🛠 Услуги",
                    callback_data="buy:cat:service",
                ),
                InlineKeyboardButton(
                    text="📦 Другое",
                    callback_data="buy:cat:other",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔎 Поиск",
                    callback_data="buy:search",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Главное меню",
                    callback_data="back_menu",
                )
            ],
        ]
    )


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐ Изменить рейтинг",
                    callback_data="admin_rating",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🖼 Водяной знак",
                    callback_data="admin_watermark",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Управление товарами",
                    callback_data="admin_products",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Главное меню",
                    callback_data="back_menu",
                )
            ],
        ]
    )


def watermark_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🖼 Установить водяной знак",
                    callback_data="watermark_set",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить водяной знак",
                    callback_data="watermark_delete",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Админ-панель",
                    callback_data="admin_panel",
                )
            ],
        ]
    )


def product_kb(
    ad_id: int,
    seller_id: int,
    viewer_id: int,
) -> InlineKeyboardMarkup:

    rows = [
        [
            InlineKeyboardButton(
                text="👤 Связаться с продавцом",
                callback_data=f"contact:{ad_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="🔙 Назад в каталог",
                callback_data="buy",
            )
        ],
    ]

    if viewer_id == seller_id or viewer_id in ADMIN_IDS:
        rows.insert(
            1,
            [
                InlineKeyboardButton(
                    text="💰 Отметить проданным",
                    callback_data=f"mark_sold:{ad_id}",
                )
            ],
        )

    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def product_list_kb(
    ads,
) -> InlineKeyboardMarkup:

    rows = []

    for ad in ads:
        kind = KIND_NAMES.get(
            ad["kind"],
            ad["kind"],
        )

        price = format_price(
            ad["price"]
        )

        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"#{ad['id']} • "
                        f"{kind} • "
                        f"{price}"
                    ),
                    callback_data=f"product:{ad['id']}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="🔎 Поиск",
                callback_data="buy:search",
            ),
            InlineKeyboardButton(
                text="📂 Категории",
                callback_data="buy",
            ),
        ]
    )

    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


# ============================================================
# БАЗА ДАННЫХ
# ============================================================


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                rating REAL NOT NULL DEFAULT 5.0,
                rating_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )

        await db.execute(
            """
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
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )

        await db.commit()


async def save_user(user):
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute(
            """
            INSERT INTO users(
                user_id,
                username,
                first_name,
                created_at
            )
            VALUES(?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name
            """,
            (
                user.id,
                user.username or "",
                user.first_name or "",
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ),
        )

        await db.commit()


async def get_user_rating(
    user_id: int,
):
    async with aiosqlite.connect(DB_PATH) as db:

        cur = await db.execute(
            """
            SELECT rating, rating_count
            FROM users
            WHERE user_id=?
            """,
            (user_id,),
        )

        row = await cur.fetchone()

    if not row:
        return 5.0, 0

    return (
        float(row[0]),
        int(row[1]),
    )


async def set_user_rating(
    user_id: int,
    rating: float,
):
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute(
            """
            INSERT INTO users(
                user_id,
                username,
                first_name,
                rating,
                rating_count,
                created_at
            )
            VALUES(?, '', '', ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                rating=excluded.rating,
                rating_count=1
            """,
            (
                user_id,
                rating,
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ),
        )

        await db.commit()


async def create_ad(
    data,
    user_id: int,
    username: str | None,
):
    async with aiosqlite.connect(DB_PATH) as db:

        cur = await db.execute(
            """
            INSERT INTO ads(
                user_id,
                username,
                kind,
                game,
                description,
                contact,
                payment,
                price,
                status,
                created_at,
                media_json
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
                datetime.now(
                    timezone.utc
                ).isoformat(),
                json.dumps(
                    data.get("media", []),
                    ensure_ascii=False,
                ),
            ),
        )

        await db.commit()

        return cur.lastrowid


async def get_ad(
    ad_id: int,
):
    async with aiosqlite.connect(DB_PATH) as db:

        db.row_factory = aiosqlite.Row

        cur = await db.execute(
            """
            SELECT *
            FROM ads
            WHERE id=?
            """,
            (ad_id,),
        )

        return await cur.fetchone()


async def set_status(
    ad_id: int,
    status: str,
):
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute(
            """
            UPDATE ads
            SET status=?
            WHERE id=?
            """,
            (
                status,
                ad_id,
            ),
        )

        await db.commit()


async def set_published(
    ad_id: int,
    message_id: int,
):
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute(
            """
            UPDATE ads
            SET status='published',
                published_message_id=?
            WHERE id=?
            """,
            (
                message_id,
                ad_id,
            ),
        )

        await db.commit()


async def update_ad_media(
    ad_id: int,
    media,
):
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute(
            """
            UPDATE ads
            SET media_json=?
            WHERE id=?
            """,
            (
                json.dumps(
                    media,
                    ensure_ascii=False,
                ),
                ad_id,
            ),
        )

        await db.commit()


async def get_setting(
    key: str,
    default: str = "",
):
    async with aiosqlite.connect(DB_PATH) as db:

        cur = await db.execute(
            """
            SELECT value
            FROM settings
            WHERE key=?
            """,
            (key,),
        )

        row = await cur.fetchone()

    if not row:
        return default

    return row[0]


async def set_setting(
    key: str,
    value: str,
):
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute(
            """
            INSERT INTO settings(key, value)
            VALUES(?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value
            """,
            (
                key,
                value,
            ),
        )

        await db.commit()


async def get_published_ads(
    kind: str | None = None,
    search: str | None = None,
    limit: int = 30,
):
    async with aiosqlite.connect(DB_PATH) as db:

        db.row_factory = aiosqlite.Row

        if kind and kind != "all":

            if search:

                pattern = f"%{search}%"

                cur = await db.execute(
                    """
                    SELECT *
                    FROM ads
                    WHERE status='published'
                      AND kind=?
                      AND (
                          game LIKE ?
                          OR description LIKE ?
                      )
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (
                        kind,
                        pattern,
                        pattern,
                        limit,
                    ),
                )

            else:

                cur = await db.execute(
                    """
                    SELECT *
                    FROM ads
                    WHERE status='published'
                      AND kind=?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (
                        kind,
                        limit,
                    ),
                )

        else:

            if search:

                pattern = f"%{search}%"

                cur = await db.execute(
                    """
                    SELECT *
                    FROM ads
                    WHERE status='published'
                      AND (
                          game LIKE ?
                          OR description LIKE ?
                          OR username LIKE ?
                      )
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (
                        pattern,
                        pattern,
                        pattern,
                        limit,
                    ),
                )

            else:

                cur = await db.execute(
                    """
                    SELECT *
                    FROM ads
                    WHERE status='published'
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )

        return await cur.fetchall()


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def format_price(
    price,
) -> str:
    value = float(price)

    if value.is_integer():
        return f"{value:.0f} ₽"

    return f"{value:.2f} ₽"


def seller_label(
    ad,
) -> str:

    username = (
        ad["username"] or ""
    ).strip()

    if username:
        return (
            "@"
            + username.lstrip("@")
        )

    return "не указан"


def rating_text(
    rating: float,
) -> str:
    return f"{rating:.1f}".replace(
        ".",
        ",",
    )


def moderation_text(
    ad,
    media_count: int,
) -> str:

    seller = seller_label(ad)

    rating, _ = (5.0, 0)

    return (
        f"🆕 <b>НОВАЯ ЗАЯВКА "
        f"НА ПУБЛИКАЦИЮ #{ad['id']}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>ПРОДАВЕЦ:</b>\n"
        f"├ Юзернейм: {seller}\n"
        f"├ ID: <code>{ad['user_id']}</code>\n"
        f"└ Контакт: "
        f"{escape(ad['contact'])}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>ИНФОРМАЦИЯ О ТОВАРЕ:</b>\n"
        f"├ Вид: "
        f"{escape(KIND_NAMES.get(ad['kind'], ad['kind']))}\n"
        f"├ Игра: "
        f"{escape(ad['game'])}\n"
        f"└ Описание: "
        f"{escape(ad['description'])}\n\n"
        f"💰 <b>ЦЕНА:</b> "
        f"{format_price(ad['price'])}\n"
        f"💳 <b>Оплата:</b> "
        f"{escape(PAY_NAMES.get(ad['payment'], ad['payment']))}\n"
        f"📸 <b>Медиа:</b> "
        f"{media_count}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Выберите действие:"
    )


def channel_post_text(
    ad,
    rating: float,
) -> str:

    kind = KIND_NAMES.get(
        ad["kind"],
        ad["kind"],
    )

    emoji = KIND_EMOJI.get(
        ad["kind"],
        "📦",
    )

    price = format_price(
        ad["price"]
    )

    seller = seller_label(ad)

    return (
        f"📦<b>Товар #{ad['id']} — "
        f"{escape(kind)} {emoji}</b>\n"
        f"🎮<b>Игра:</b> "
        f"{escape(ad['game'])};\n"
        f"👑<b>Статус:</b> "
        f"Не продан;\n"
        f"💰<b>Цена:</b> "
        f"{price};\n"
        f"💳<b>Способ оплаты:</b> "
        f"{escape(PAY_NAMES.get(ad['payment'], ad['payment']))}.\n\n"
        f"👤<b>Продавец "
        f"(SMDC {rating_text(rating)}/5):</b> "
        f"{escape(seller)}\n\n"
        f"📖<b>Информация о товаре:</b> "
        f"{escape(ad['description'])}\n\n"
        f"🔎<b>Ссылка на пост:</b> "
        f'<a href="https://t.me/smdcshop">SMDC</a>.'
    )


def make_post_link(
    channel: str,
    message_id: int,
) -> str | None:

    if PUBLIC_CHANNEL_URL:

        base = PUBLIC_CHANNEL_URL.rstrip("/")

        return (
            f"{base}/{message_id}"
        )

    if channel.startswith("@"):

        return (
            f"https://t.me/"
            f"{channel[1:]}/"
            f"{message_id}"
        )

    return None


async def await_dummy_rating_placeholder():
    return 5.0, 0


# ============================================================
# ВОДЯНОЙ ЗНАК
# ============================================================


async def process_photo_with_watermark(
    file_id: str,
):
    watermark_id = await get_setting(
        "watermark_file_id",
        "",
    )

    if not watermark_id:
        return file_id

    try:
        from PIL import Image

        original_info = await bot.get_file(
            file_id
        )

        original_data = BytesIO()

        await bot.download_file(
            original_info.file_path,
            destination=original_data,
        )

        watermark_info = await bot.get_file(
            watermark_id
        )

        watermark_data = BytesIO()

        await bot.download_file(
            watermark_info.file_path,
            destination=watermark_data,
        )

        base = Image.open(
            BytesIO(
                original_data.getvalue()
            )
        ).convert("RGBA")

        mark = Image.open(
            BytesIO(
                watermark_data.getvalue()
            )
        ).convert("RGBA")

        target_width = max(
            1,
            int(base.width * 0.28),
        )

        target_height = max(
            1,
            int(
                mark.height
                * target_width
                / mark.width
            ),
        )

        mark.thumbnail(
            (
                target_width,
                target_height,
            ),
            Image.Resampling.LANCZOS,
        )

        alpha = mark.getchannel(
            "A"
        ).point(
            lambda value: int(
                value * 0.55
            )
        )

        mark.putalpha(alpha)

        margin = max(
            10,
            int(base.width * 0.025),
        )

        position = (
            base.width
            - mark.width
            - margin,
            base.height
            - mark.height
            - margin,
        )

        base.alpha_composite(
            mark,
            position,
        )

        output = BytesIO()

        base.convert("RGB").save(
            output,
            format="JPEG",
            quality=92,
        )

        return BufferedInputFile(
            output.getvalue(),
            filename="watermarked.jpg",
        )

    except Exception:
        logging.exception(
            "Ошибка обработки водяного знака"
        )

        return file_id


async def send_channel_ad(
    ad,
):
    media = json.loads(
        ad["media_json"] or "[]"
    )

    rating, _ = await get_user_rating(
        ad["user_id"]
    )

    caption = channel_post_text(
        ad,
        rating,
    )

    sent_message = None

    if media:

        first = media[0]

        if first["type"] == "photo":

            photo = (
                await process_photo_with_watermark(
                    first["file_id"]
                )
            )

            sent_message = await bot.send_photo(
                PUBLIC_CHANNEL,
                photo,
                caption=caption,
            )

        elif first["type"] == "video":

            sent_message = await bot.send_video(
                PUBLIC_CHANNEL,
                first["file_id"],
                caption=caption,
            )

        for item in media[1:]:

            if item["type"] == "photo":

                photo = (
                    await process_photo_with_watermark(
                        item["file_id"]
                    )
                )

                await bot.send_photo(
                    PUBLIC_CHANNEL,
                    photo,
                )

            elif item["type"] == "video":

                await bot.send_video(
                    PUBLIC_CHANNEL,
                    item["file_id"],
                )

    else:

        sent_message = await bot.send_message(
            PUBLIC_CHANNEL,
            caption,
        )

    return sent_message


# ============================================================
# START
# ============================================================


@router.message(CommandStart())
async def start(
    message: Message,
    state: FSMContext,
):
    await state.clear()

    await save_user(
        message.from_user
    )

    await message.answer(
        "🛒 <b>Super Mechs Market</b>\n\n"
        "Добро пожаловать!\n"
        "Здесь можно покупать и выставлять товары.",
        reply_markup=main_menu(
            message.from_user.id
        ),
    )


# ============================================================
# ПРОДАЖА
# ============================================================


@router.callback_query(
    F.data == "sell"
)
async def sell_start(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.clear()

    await state.set_state(
        SellForm.kind
    )

    await callback.message.edit_text(
        "🔥 <b>ВЫСТАВЛЕНИЕ ТОВАРА</b>\n\n"
        "⚠️ Объявление пройдёт модерацию.\n\n"
        "<b>Шаг 1 из 7</b>\n"
        "Выберите вид товара:",
        reply_markup=kind_kb(),
    )

    await callback.answer()


@router.callback_query(
    F.data.startswith("kind:")
)
async def sell_kind(
    callback: CallbackQuery,
    state: FSMContext,
):

    kind = callback.data.split(
        ":",
        1,
    )[1]

    if kind not in KIND_NAMES:
        await callback.answer(
            "Неизвестный вид товара.",
            show_alert=True,
        )
        return

    await state.update_data(
        kind=kind
    )

    await state.set_state(
        SellForm.game
    )

    await callback.message.edit_text(
        f"✅ Вид товара: "
        f"<b>{KIND_NAMES[kind]}</b>\n\n"
        "<b>Шаг 2 из 7</b>\n"
        "Укажите игру.\n\n"
        "Пример: <i>Super Mechs</i>",
        reply_markup=cancel_kb(),
    )

    await callback.answer()


@router.message(
    SellForm.game
)
async def sell_game(
    message: Message,
    state: FSMContext,
):

    text = (
        message.text or ""
    ).strip()

    if not text:
        await message.answer(
            "❌ Напишите название игры."
        )
        return

    await state.update_data(
        game=text
    )

    await state.set_state(
        SellForm.description
    )

    await message.answer(
        "✅ Игра сохранена.\n\n"
        "<b>Шаг 3 из 7</b>\n"
        "Введите описание товара.",
        reply_markup=cancel_kb(),
    )


@router.message(
    SellForm.description
)
async def sell_description(
    message: Message,
    state: FSMContext,
):

    text = (
        message.text or ""
    ).strip()

    if not text:
        await message.answer(
            "❌ Описание не может быть пустым."
        )
        return

    await state.update_data(
        description=text,
        media=[],
    )

    await state.set_state(
        SellForm.media
    )

    await message.answer(
        "✅ Описание сохранено.\n\n"
        "<b>Шаг 4 из 7</b>\n"
        "Отправьте фото или видео товара.\n"
        "Можно несколько.\n\n"
        "После последнего файла нажмите /done.",
        reply_markup=cancel_kb(),
    )


@router.message(
    SellForm.media,
    F.content_type.in_(
        {
            ContentType.PHOTO,
            ContentType.VIDEO,
        }
    ),
)
async def sell_media(
    message: Message,
    state: FSMContext,
):

    data = await state.get_data()

    media = data.get(
        "media",
        [],
    )

    if message.photo:

        media.append(
            {
                "type": "photo",
                "file_id": (
                    message.photo[-1].file_id
                ),
            }
        )

    elif message.video:

        media.append(
            {
                "type": "video",
                "file_id": (
                    message.video.file_id
                ),
            }
        )

    await state.update_data(
        media=media
    )

    await message.answer(
        f"📸 Медиафайл "
        f"#{len(media)} добавлен.\n\n"
        "Отправьте следующий файл "
        "или нажмите /done."
    )


@router.message(
    SellForm.media,
    Command("done"),
)
async def sell_media_done(
    message: Message,
    state: FSMContext,
):

    data = await state.get_data()

    if not data.get("media"):
        await message.answer(
            "⚠️ Добавьте хотя бы одно "
            "фото или видео."
        )
        return

    await state.set_state(
        SellForm.contact
    )

    await message.answer(
        "<b>Шаг 5 из 7</b>\n"
        "Введите контакт для связи.\n\n"
        "Например: @username",
        reply_markup=cancel_kb(),
    )


@router.message(
    SellForm.media
)
async def sell_media_wrong(
    message: Message,
):

    await message.answer(
        "📸 Отправьте фото/видео "
        "или нажмите /done."
    )


@router.message(
    SellForm.contact
)
async def sell_contact(
    message: Message,
    state: FSMContext,
):

    text = (
        message.text or ""
    ).strip()

    if not text:
        await message.answer(
            "❌ Введите контакт."
        )
        return

    await state.update_data(
        contact=text
    )

    await state.set_state(
        SellForm.payment
    )

    await message.answer(
        "<b>Шаг 6 из 7</b>\n"
        "Выберите способ оплаты:",
        reply_markup=payment_kb(),
    )


@router.callback_query(
    SellForm.payment,
    F.data.startswith("pay:"),
)
async def sell_payment(
    callback: CallbackQuery,
    state: FSMContext,
):

    payment = callback.data.split(
        ":",
        1,
    )[1]

    if payment not in PAY_NAMES:
        await callback.answer(
            "Неизвестный способ оплаты.",
            show_alert=True,
        )
        return

    await state.update_data(
        payment=payment
    )

    await state.set_state(
        SellForm.price
    )

    await callback.message.edit_text(
        f"✅ Способ оплаты: "
        f"<b>{escape(PAY_NAMES[payment])}</b>\n\n"
        "<b>Шаг 7 из 7</b>\n"
        "Введите цену в рублях.\n\n"
        "Например: <code>357</code>",
        reply_markup=cancel_kb(),
    )

    await callback.answer()


@router.message(
    SellForm.price
)
async def sell_price(
    message: Message,
    state: FSMContext,
):

    raw = (
        message.text or ""
    ).replace(
        ",",
        ".",
    ).replace(
        "₽",
        "",
    ).strip()

    try:

        price = float(raw)

        if (
            price <= 0
            or price > 10_000_000
        ):
            raise ValueError

    except ValueError:

        await message.answer(
            "❌ Введите корректную цену, "
            "например <code>357</code>."
        )

        return

    data = await state.get_data()

    data["price"] = price

    ad_id = await create_ad(
        data,
        message.from_user.id,
        message.from_user.username,
    )

    ad = await get_ad(
        ad_id
    )

    media_count = len(
        data.get(
            "media",
            [],
        )
    )

    text = moderation_text(
        ad,
        media_count,
    )

    if not ADMIN_IDS:

        await set_status(
            ad_id,
            "error",
        )

        await message.answer(
            "⚠️ Заявка создана, "
            "но ADMIN_IDS не настроен.\n\n"
            "Администраторы не получили заявку."
        )

        await state.clear()

        return

    for admin_id in ADMIN_IDS:

        try:

            await bot.send_message(
                admin_id,
                text,
                reply_markup=admin_kb(
                    ad_id
                ),
            )

            for item in data.get(
                "media",
                [],
            ):

                if item["type"] == "photo":

                    await bot.send_photo(
                        admin_id,
                        item["file_id"],
                    )

                elif item["type"] == "video":

                    await bot.send_video(
                        admin_id,
                        item["file_id"],
                    )

        except Exception:

            logging.exception(
                "Не удалось отправить "
                "заявку администратору %s",
                admin_id,
            )

    await state.clear()

    await message.answer(
        f"✅ <b>ЗАЯВКА #{ad_id} "
        f"ОТПРАВЛЕНА НА МОДЕРАЦИЮ!</b>\n\n"
        "⏱ Ожидайте решения администратора.\n"
        "📋 Статус можно посмотреть "
        "в «Мои объявления».",
        reply_markup=main_menu(
            message.from_user.id
        ),
    )


@router.callback_query(
    F.data == "cancel_sell"
)
async def cancel_sell(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.clear()

    await callback.message.edit_text(
        "❌ Выставление товара отменено.",
        reply_markup=main_menu(
            callback.from_user.id
        ),
    )

    await callback.answer()


# ============================================================
# КАТАЛОГ
# ============================================================


@router.callback_query(
    F.data == "buy"
)
async def buy(
    callback: CallbackQuery,
):

    await callback.message.edit_text(
        "🛍 <b>МАГАЗИН</b>\n\n"
        "Выберите категорию или воспользуйтесь поиском.",
        reply_markup=buy_categories_kb(),
    )

    await callback.answer()


@router.callback_query(
    F.data.startswith("buy:cat:")
)
async def buy_category(
    callback: CallbackQuery,
):

    kind = callback.data.split(
        ":",
        2,
    )[2]

    ads = await get_published_ads(
        kind=kind
    )

    if not ads:

        await callback.message.edit_text(
            "🛍 <b>МАГАЗИН</b>\n\n"
            "В этой категории пока "
            "нет доступных товаров.",
            reply_markup=buy_categories_kb(),
        )

        await callback.answer()

        return

    title = (
        "Все товары"
        if kind == "all"
        else KIND_NAMES.get(
            kind,
            kind,
        )
    )

    await callback.message.edit_text(
        f"🛍 <b>{escape(title)}</b>\n\n"
        f"Доступно товаров: <b>{len(ads)}</b>\n\n"
        "Нажмите на товар для просмотра:",
        reply_markup=product_list_kb(
            ads
        ),
    )

    await callback.answer()


@router.callback_query(
    F.data == "buy:search"
)
async def buy_search_start(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.clear()

    await state.set_state(
        BuySearch.query
    )

    await callback.message.edit_text(
        "🔎 <b>ПОИСК ТОВАРОВ</b>\n\n"
        "Введите название игры, "
        "описание или часть названия товара.\n\n"
        "Например: <code>Super Mechs</code>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data="buy",
                    )
                ]
            ]
        ),
    )

    await callback.answer()


@router.message(
    BuySearch.query
)
async def buy_search_result(
    message: Message,
    state: FSMContext,
):

    query = (
        message.text or ""
    ).strip()

    if not query:

        await message.answer(
            "❌ Введите поисковый запрос."
        )

        return

    ads = await get_published_ads(
        search=query
    )

    await state.clear()

    if not ads:

        await message.answer(
            "🔎 <b>Ничего не найдено.</b>\n\n"
            "Попробуйте другой запрос.",
            reply_markup=buy_categories_kb(),
        )

        return

    await message.answer(
        f"🔎 <b>Результаты поиска:</b> "
        f"{escape(query)}\n\n"
        f"Найдено: <b>{len(ads)}</b>",
        reply_markup=product_list_kb(
            ads
        ),
    )


@router.callback_query(
    F.data.startswith("product:")
)
async def product_details(
    callback: CallbackQuery,
):

    try:

        ad_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )

    except ValueError:

        await callback.answer(
            "Ошибка товара.",
            show_alert=True,
        )

        return

    ad = await get_ad(
        ad_id
    )

    if not ad or ad["status"] != "published":

        await callback.answer(
            "Товар больше недоступен.",
            show_alert=True,
        )

        return

    rating, _ = await get_user_rating(
        ad["user_id"]
    )

    seller = seller_label(ad)

    price = format_price(
        ad["price"]
    )

    text = (
        f"📦 <b>Товар #{ad['id']}</b>\n\n"
        f"🪪 <b>Вид:</b> "
        f"{escape(KIND_NAMES.get(ad['kind'], ad['kind']))}\n"
        f"🎮 <b>Игра:</b> "
        f"{escape(ad['game'])}\n"
        f"👑 <b>Статус:</b> Не продан\n"
        f"💰 <b>Цена:</b> {price}\n"
        f"💳 <b>Оплата:</b> "
        f"{escape(PAY_NAMES.get(ad['payment'], ad['payment']))}\n\n"
        f"👤 <b>Продавец:</b> "
        f"{escape(seller)}\n"
        f"⭐ <b>Рейтинг SMDC:</b> "
        f"{rating_text(rating)}/5\n\n"
        f"📖 <b>Описание:</b>\n"
        f"{escape(ad['description'])}"
    )

    media = json.loads(
        ad["media_json"] or "[]"
    )

    if media:

        first = media[0]

        try:

            if first["type"] == "photo":

                await callback.message.answer_photo(
                    first["file_id"]
                )

            elif first["type"] == "video":

                await callback.message.answer_video(
                    first["file_id"]
                )

        except Exception:

            logging.exception(
                "Не удалось показать медиа товара #%s",
                ad_id,
            )

    await callback.message.answer(
        text,
        reply_markup=product_kb(
            ad_id,
            ad["user_id"],
            callback.from_user.id,
        ),
    )

    await callback.answer()


@router.callback_query(
    F.data.startswith("contact:")
)
async def contact_seller(
    callback: CallbackQuery,
):

    try:

        ad_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )

    except ValueError:

        await callback.answer(
            "Ошибка.",
            show_alert=True,
        )

        return

    ad = await get_ad(
        ad_id
    )

    if not ad or ad["status"] != "published":

        await callback.answer(
            "Товар больше недоступен.",
            show_alert=True,
        )

        return

    contact = escape(
        ad["contact"]
    )

    await callback.message.answer(
        "👤 <b>Контакт продавца</b>\n\n"
        f"{contact}\n\n"
        "Связывайтесь с продавцом "
        "по указанному контакту.",
    )

    await callback.answer()


@router.callback_query(
    F.data.startswith("mark_sold:")
)
async def mark_sold(
    callback: CallbackQuery,
):

    try:

        ad_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )

    except ValueError:

        await callback.answer(
            "Ошибка.",
            show_alert=True,
        )

        return

    ad = await get_ad(
        ad_id
    )

    if not ad:

        await callback.answer(
            "Товар не найден.",
            show_alert=True,
        )

        return

    if (
        callback.from_user.id
        != ad["user_id"]
        and callback.from_user.id
        not in ADMIN_IDS
    ):

        await callback.answer(
            "⛔ Нет прав.",
            show_alert=True,
        )

        return

    await set_status(
        ad_id,
        "sold",
    )

    await callback.message.edit_text(
        "💰 <b>Товар отмечен как проданный.</b>\n\n"
        f"Товар #{ad_id} больше "
        "не отображается в каталоге.",
        reply_markup=main_menu(
            callback.from_user.id
        ),
    )

    await callback.answer(
        "Товар отмечен проданным."
    )


# ============================================================
# ПРОФИЛЬ
# ============================================================


@router.callback_query(
    F.data == "profile"
)
async def profile(
    callback: CallbackQuery,
):

    await save_user(
        callback.from_user
    )

    rating, rating_count = (
        await get_user_rating(
            callback.from_user.id
        )
    )

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        cur = await db.execute(
            """
            SELECT COUNT(*)
            FROM ads
            WHERE user_id=?
            """,
            (
                callback.from_user.id,
            ),
        )

        count = (
            await cur.fetchone()
        )[0]

    username = (
        callback.from_user.username
        or "не указан"
    )

    text = (
        "👤 <b>МОЙ ПРОФИЛЬ</b>\n\n"
        f"ID: <code>{callback.from_user.id}</code>\n"
        f"Username: @{escape(username)}\n"
        f"⭐ Рейтинг SMDC: "
        f"{rating_text(rating)}/5"
    )

    if rating_count:

        text += (
            f" ({rating_count} оценок)"
        )

    text += (
        f"\n📦 Объявлений: {count}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu(
            callback.from_user.id
        ),
    )

    await callback.answer()


# ============================================================
# МОИ ОБЪЯВЛЕНИЯ
# ============================================================


@router.callback_query(
    F.data == "my_ads"
)
async def my_ads(
    callback: CallbackQuery,
):

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        db.row_factory = aiosqlite.Row

        cur = await db.execute(
            """
            SELECT id,
                   kind,
                   game,
                   price,
                   status
            FROM ads
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 30
            """,
            (
                callback.from_user.id,
            ),
        )

        rows = await cur.fetchall()

    if not rows:

        text = (
            "📋 <b>МОИ ОБЪЯВЛЕНИЯ</b>\n\n"
            "У вас пока нет объявлений."
        )

    else:

        parts = [
            "📋 <b>МОИ ОБЪЯВЛЕНИЯ</b>\n"
        ]

        for row in rows:

            price = format_price(
                row["price"]
            )

            status = STATUS_NAMES.get(
                row["status"],
                row["status"],
            )

            parts.append(
                f"📦 <b>Товар #{row['id']}</b>\n"
                f"├ "
                f"{escape(KIND_NAMES.get(row['kind'], row['kind']))}\n"
                f"├ "
                f"{escape(row['game'])}\n"
                f"├ {price}\n"
                f"└ {status}\n"
            )

        text = "\n".join(
            parts
        )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu(
            callback.from_user.id
        ),
    )

    await callback.answer()


# ============================================================
# ПРАВИЛА
# ============================================================


@router.callback_query(
    F.data == "rules"
)
async def rules(
    callback: CallbackQuery,
):

    await callback.message.edit_text(
        "ℹ️ <b>ПРАВИЛА</b>\n\n"
        "1. Публикуйте только реальные объявления.\n"
        "2. Все объявления проходят модерацию.\n"
        "3. Запрещённые товары и услуги не публикуются.\n"
        "4. Не отправляйте лишние персональные данные.\n"
        "5. Администрация может отклонить объявление.\n"
        "6. Не вводите покупателей в заблуждение.\n"
        "7. После продажи обязательно отметьте товар проданным.",
        reply_markup=main_menu(
            callback.from_user.id
        ),
    )

    await callback.answer()


# ============================================================
# ПОДДЕРЖКА
# ============================================================


@router.callback_query(
    F.data == "support"
)
async def support(
    callback: CallbackQuery,
):

    await callback.message.edit_text(
        "🆘 <b>ПОДДЕРЖКА</b>\n\n"
        "По вопросам работы магазина "
        "обратитесь к администрации.",
        reply_markup=main_menu(
            callback.from_user.id
        ),
    )

    await callback.answer()


# ============================================================
# АДМИН-ПАНЕЛЬ
# ============================================================


@router.callback_query(
    F.data == "admin_panel"
)
async def admin_panel(
    callback: CallbackQuery,
):

    if callback.from_user.id not in ADMIN_IDS:

        await callback.answer(
            "⛔ Нет прав администратора.",
            show_alert=True,
        )

        return

    watermark = await get_setting(
        "watermark_file_id",
        "",
    )

    watermark_status = (
        "установлен"
        if watermark
        else "не установлен"
    )

    await callback.message.edit_text(
        "⚙️ <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        f"🖼 Водяной знак: "
        f"<b>{watermark_status}</b>\n\n"
        "Здесь можно управлять "
        "рейтингами, водяным знаком "
        "и товарами.",
        reply_markup=admin_panel_kb(),
    )

    await callback.answer()


# ============================================================
# АДМИН — РЕЙТИНГ
# ============================================================


@router.callback_query(
    F.data == "admin_rating"
)
async def admin_rating_start(
    callback: CallbackQuery,
    state: FSMContext,
):

    if callback.from_user.id not in ADMIN_IDS:

        await callback.answer(
            "⛔ Нет прав.",
            show_alert=True,
        )

        return

    await state.clear()

    await state.set_state(
        AdminRating.user_id
    )

    await callback.message.edit_text(
        "⭐ <b>ИЗМЕНЕНИЕ РЕЙТИНГА</b>\n\n"
        "Введите Telegram ID продавца.\n\n"
        "Например:\n"
        "<code>1955966085</code>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data="admin_panel",
                    )
                ]
            ]
        ),
    )

    await callback.answer()


@router.message(
    AdminRating.user_id
)
async def admin_rating_user(
    message: Message,
    state: FSMContext,
):

    raw = (
        message.text or ""
    ).strip()

    try:

        user_id = int(raw)

    except ValueError:

        await message.answer(
            "❌ ID должен состоять только из цифр."
        )

        return

    await state.update_data(
        user_id=user_id
    )

    await state.set_state(
        AdminRating.rating
    )

    await message.answer(
        "⭐ Теперь введите новый рейтинг.\n\n"
        "Допустимый диапазон: "
        "<code>0</code> — <code>5</code>\n\n"
        "Например: <code>3.8</code>"
    )


@router.message(
    AdminRating.rating
)
async def admin_rating_value(
    message: Message,
    state: FSMContext,
):

    raw = (
        message.text or ""
    ).replace(
        ",",
        ".",
    ).strip()

    try:

        rating = float(raw)

        if (
            rating < 0
            or rating > 5
        ):
            raise ValueError

    except ValueError:

        await message.answer(
            "❌ Рейтинг должен быть "
            "числом от 0 до 5.\n\n"
            "Например: <code>3.8</code>"
        )

        return

    data = await state.get_data()

    user_id = int(
        data["user_id"]
    )

    await set_user_rating(
        user_id,
        rating,
    )

    await state.clear()

    await message.answer(
        "✅ <b>Рейтинг изменён.</b>\n\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"⭐ Новый рейтинг: "
        f"<b>{rating_text(rating)}/5</b>",
        reply_markup=main_menu(
            message.from_user.id
        ),
    )


# ============================================================
# АДМИН — ВОДЯНОЙ ЗНАК
# ============================================================


@router.callback_query(
    F.data == "admin_watermark"
)
async def admin_watermark(
    callback: CallbackQuery,
):

    if callback.from_user.id not in ADMIN_IDS:

        await callback.answer(
            "⛔ Нет прав.",
            show_alert=True,
        )

        return

    watermark = await get_setting(
        "watermark_file_id",
        "",
    )

    status = (
        "🟢 установлен"
        if watermark
        else "🔴 не установлен"
    )

    await callback.message.edit_text(
        "🖼 <b>ВОДЯНОЙ ЗНАК</b>\n\n"
        f"Статус: {status}\n\n"
        "Водяной знак автоматически "
        "накладывается на фотографии "
        "перед публикацией товара в канал.\n\n"
        "Видео не изменяются.",
        reply_markup=watermark_kb(),
    )

    await callback.answer()


@router.callback_query(
    F.data == "watermark_set"
)
async def watermark_set(
    callback: CallbackQuery,
    state: FSMContext,
):

    if callback.from_user.id not in ADMIN_IDS:

        await callback.answer(
            "⛔ Нет прав.",
            show_alert=True,
        )

        return

    await state.clear()

    await state.set_state(
        AdminWatermark.photo
    )

    await callback.message.edit_text(
        "🖼 <b>УСТАНОВКА ВОДЯНОГО ЗНАКА</b>\n\n"
        "Отправьте сюда фотографию, "
        "которая будет использоваться "
        "как водяной знак.\n\n"
        "Лучше использовать PNG "
        "с прозрачным фоном.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data="admin_watermark",
                    )
                ]
            ]
        ),
    )

    await callback.answer()


@router.message(
    AdminWatermark.photo,
    F.photo,
)
async def watermark_photo(
    message: Message,
    state: FSMContext,
):

    if message.from_user.id not in ADMIN_IDS:

        await state.clear()

        return

    file_id = (
        message.photo[-1].file_id
    )

    await set_setting(
        "watermark_file_id",
        file_id,
    )

    await state.clear()

    await message.answer(
        "✅ <b>Водяной знак сохранён.</b>\n\n"
        "Теперь фотографии новых "
        "публикаций будут автоматически "
        "получать этот водяной знак.",
        reply_markup=main_menu(
            message.from_user.id
        ),
    )


@router.message(
    AdminWatermark.photo
)
async def watermark_wrong(
    message: Message,
):

    await message.answer(
        "🖼 Отправьте именно фотографию "
        "водяного знака."
    )


@router.callback_query(
    F.data == "watermark_delete"
)
async def watermark_delete(
    callback: CallbackQuery,
):

    if callback.from_user.id not in ADMIN_IDS:

        await callback.answer(
            "⛔ Нет прав.",
            show_alert=True,
        )

        return

    await set_setting(
        "watermark_file_id",
        "",
    )

    await callback.message.edit_text(
        "🗑 <b>Водяной знак удалён.</b>\n\n"
        "Новые фотографии будут "
        "публиковаться без водяного знака.",
        reply_markup=admin_panel_kb(),
    )

    await callback.answer(
        "Водяной знак удалён."
    )


# ============================================================
# АДМИН — ЗАМЕНА ФОТО
# ============================================================


@router.callback_query(
    F.data.startswith("replace_photo:")
)
async def replace_photo_start(
    callback: CallbackQuery,
    state: FSMContext,
):

    if callback.from_user.id not in ADMIN_IDS:

        await callback.answer(
            "⛔ Нет прав.",
            show_alert=True,
        )

        return

    try:

        ad_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )

    except ValueError:

        await callback.answer(
            "Ошибка объявления.",
            show_alert=True,
        )

        return

    ad = await get_ad(
        ad_id
    )

    if not ad:

        await callback.answer(
            "Объявление не найдено.",
            show_alert=True,
        )

        return

    await state.clear()

    await state.update_data(
        ad_id=ad_id
    )

    await state.set_state(
        AdminReplacePhoto.ad_id
    )

    await callback.message.answer(
        f"🖼 <b>ЗАМЕНА ГЛАВНОГО ФОТО</b>\n\n"
        f"Товар #{ad_id}\n\n"
        "Отправьте новую фотографию.\n"
        "Она станет главным фото объявления."
    )

    await callback.answer()


@router.message(
    AdminReplacePhoto.ad_id,
    F.photo,
)
async def replace_photo_receive(
    message: Message,
    state: FSMContext,
):

    if message.from_user.id not in ADMIN_IDS:

        await state.clear()

        return

    data = await state.get_data()

    ad_id = int(
        data["ad_id"]
    )

    ad = await get_ad(
        ad_id
    )

    if not ad:

        await state.clear()

        await message.answer(
            "❌ Объявление не найдено."
        )

        return

    media = json.loads(
        ad["media_json"] or "[]"
    )

    new_photo = {
        "type": "photo",
        "file_id": (
            message.photo[-1].file_id
        ),
    }

    if media:

        media[0] = new_photo

    else:

        media = [
            new_photo
        ]

    await update_ad_media(
        ad_id,
        media,
    )

    await state.clear()

    await message.answer(
        f"✅ <b>Главное фото товара "
        f"#{ad_id} заменено.</b>\n\n"
        "Если товар будет опубликован "
        "после этого, на новое фото "
        "автоматически будет нанесён "
        "водяной знак, если он установлен.",
        reply_markup=main_menu(
            message.from_user.id
        ),
    )


@router.message(
    AdminReplacePhoto.ad_id
)
async def replace_photo_wrong(
    message: Message,
):

    await message.answer(
        "🖼 Отправьте фотографию."
    )


# ============================================================
# АДМИН — ТОВАРЫ
# ============================================================


@router.callback_query(
    F.data == "admin_products"
)
async def admin_products(
    callback: CallbackQuery,
):

    if callback.from_user.id not in ADMIN_IDS:

        await callback.answer(
            "⛔ Нет прав.",
            show_alert=True,
        )

        return

    async with aiosqlite.connect(
        DB_PATH
    ) as db:

        db.row_factory = aiosqlite.Row

        cur = await db.execute(
            """
            SELECT id,
                   kind,
                   game,
                   price,
                   status
            FROM ads
            ORDER BY id DESC
            LIMIT 30
            """
        )

        rows = await cur.fetchall()

    if not rows:

        text = (
            "📦 <b>ТОВАРЫ</b>\n\n"
            "Товаров пока нет."
        )

        await callback.message.edit_text(
            text,
            reply_markup=admin_panel_kb(),
        )

        await callback.answer()

        return

    parts = [
        "📦 <b>ПОСЛЕДНИЕ ТОВАРЫ</b>\n"
    ]

    for row in rows:

        parts.append(
            f"#{row['id']} — "
            f"{escape(KIND_NAMES.get(row['kind'], row['kind']))} — "
            f"{escape(row['game'])} — "
            f"{format_price(row['price'])} — "
            f"{STATUS_NAMES.get(row['status'], row['status'])}"
        )

    await callback.message.edit_text(
        "\n".join(parts),
        reply_markup=admin_panel_kb(),
    )

    await callback.answer()


# ============================================================
# МОДЕРАЦИЯ — ОДОБРЕНИЕ
# ============================================================


@router.callback_query(
    F.data.startswith("approve:")
)
async def approve(
    callback: CallbackQuery,
):

    if callback.from_user.id not in ADMIN_IDS:

        await callback.answer(
            "⛔ У вас нет прав администратора.",
            show_alert=True,
        )

        return

    try:

        ad_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )

    except ValueError:

        await callback.answer(
            "Ошибка заявки.",
            show_alert=True,
        )

        return

    ad = await get_ad(
        ad_id
    )

    if (
        not ad
        or ad["status"] != "pending"
    ):

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True,
        )

        return

    if not PUBLIC_CHANNEL:

        await callback.answer(
            "PUBLIC_CHANNEL не настроен.",
            show_alert=True,
        )

        return

    try:

        sent = await send_channel_ad(
            ad
        )

    except Exception:

        logging.exception(
            "Ошибка публикации "
            "объявления #%s",
            ad_id,
        )

        await callback.answer(
            "Не удалось опубликовать. "
            "Проверьте права бота в канале "
            "и настройки.",
            show_alert=True,
        )

        return

    if not sent:

        await callback.answer(
            "Telegram не вернул сообщение публикации.",
            show_alert=True,
        )

        return

    await set_published(
        ad_id,
        sent.message_id,
    )

    link = make_post_link(
        PUBLIC_CHANNEL,
        sent.message_id,
    )

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    admin_result = (
        f"✅ <b>Товар #{ad_id} "
        f"опубликован в канале.</b>"
    )

    if link:

        admin_result += (
            f'\n🔎 <a href="{link}">'
            "Открыть пост</a>"
        )

    await callback.message.answer(
        admin_result
    )

    user_result = (
        f"✅ <b>Ваша заявка #{ad_id} "
        f"одобрена и опубликована!</b>"
    )

    if link:

        user_result += (
            f'\n🔎 <a href="{link}">'
            "Открыть объявление</a>"
        )

    try:

        await bot.send_message(
            ad["user_id"],
            user_result,
        )

    except Exception:

        logging.exception(
            "Не удалось уведомить продавца %s",
            ad["user_id"],
        )

    await callback.answer(
        "Опубликовано!"
    )


# ============================================================
# МОДЕРАЦИЯ — ОТКЛОНЕНИЕ
# ============================================================


@router.callback_query(
    F.data.startswith("reject:")
)
async def reject(
    callback: CallbackQuery,
):

    if callback.from_user.id not in ADMIN_IDS:

        await callback.answer(
            "⛔ У вас нет прав администратора.",
            show_alert=True,
        )

        return

    try:

        ad_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )

    except ValueError:

        await callback.answer(
            "Ошибка заявки.",
            show_alert=True,
        )

        return

    ad = await get_ad(
        ad_id
    )

    if (
        not ad
        or ad["status"] != "pending"
    ):

        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True,
        )

        return

    await set_status(
        ad_id,
        "rejected",
    )

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.message.answer(
        f"❌ <b>Заявка #{ad_id} "
        f"отклонена.</b>"
    )

    try:

        await bot.send_message(
            ad["user_id"],
            f"❌ <b>Ваша заявка #{ad_id} "
            f"отклонена модератором.</b>",
        )

    except Exception:

        logging.exception(
            "Не удалось уведомить продавца %s",
            ad["user_id"],
        )

    await callback.answer(
        "Отклонено."
    )


# ============================================================
# ГЛАВНОЕ МЕНЮ
# ============================================================


@router.callback_query(
    F.data == "back_menu"
)
async def back_menu(
    callback: CallbackQuery,
):

    await callback.message.edit_text(
        "🛒 <b>Super Mechs Market</b>\n\n"
        "Выберите действие:",
        reply_markup=main_menu(
            callback.from_user.id
        ),
    )

    await callback.answer()


# ============================================================
# КОМАНДЫ
# ============================================================


@router.message(
    Command("myid")
)
async def myid(
    message: Message,
):

    await message.answer(
        "🆔 <b>Ваш Telegram ID:</b>\n"
        f"<code>{message.from_user.id}</code>\n\n"
        "Добавьте этот номер в "
        "ADMIN_IDS в файле .env."
    )


@router.message(
    Command("sell")
)
async def sell_command(
    message: Message,
    state: FSMContext,
):

    await state.clear()

    await state.set_state(
        SellForm.kind
    )

    await message.answer(
        "📦 Выберите вид товара:",
        reply_markup=kind_kb(),
    )


@router.message(
    Command("cancel")
)
async def cancel_command(
    message: Message,
    state: FSMContext,
):

    await state.clear()

    await message.answer(
        "❌ Действие отменено.",
        reply_markup=main_menu(
            message.from_user.id
        ),
    )


# ============================================================
# ЗАПУСК
# ============================================================


async def main():

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(message)s"
        ),
    )

    await init_db()

    logging.info(
        "Super Mechs Market Bot запущен."
    )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":
    asyncio.run(main())