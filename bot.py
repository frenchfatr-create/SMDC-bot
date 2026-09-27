import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin

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
)

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
    raise RuntimeError("BOT_TOKEN не указан в .env")

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
router = Router()
dp.include_router(router)


class SellForm(StatesGroup):
    kind = State()
    game = State()
    description = State()
    media = State()
    contact = State()
    payment = State()
    price = State()


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
    "both": "Перевод с карты на карту или через СБП или Telegram Stars",
}


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛍 Купить", callback_data="buy"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Продать товар", callback_data="sell"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Мой профиль", callback_data="profile"
                ),
                InlineKeyboardButton(
                    text="📋 Мои объявления", callback_data="my_ads"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="ℹ️ Правила", callback_data="rules"
                ),
                InlineKeyboardButton(
                    text="🆘 Поддержка", callback_data="support"
                ),
            ],
        ]
    )


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data="cancel_sell"
                )
            ]
        ]
    )


def kind_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🪪 Аккаунт", callback_data="kind:account"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🪙 Валюта", callback_data="kind:currency"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛠 Услуга", callback_data="kind:service"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Другое", callback_data="kind:other"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data="cancel_sell"
                )
            ],
        ]
    )


def payment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Карта / СБП", callback_data="pay:card"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭐ Telegram Stars", callback_data="pay:stars"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💳 + ⭐ Оба варианта", callback_data="pay:both"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data="cancel_sell"
                )
            ],
        ]
    )


def admin_kb(ad_id: int) -> InlineKeyboardMarkup:
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
            ]
        ]
    )


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
        await db.commit()


async def save_user(user):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users(
                user_id, username, first_name, created_at
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
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()


async def get_user_rating(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT rating, rating_count FROM users WHERE user_id=?",
            (user_id,),
        )
        row = await cur.fetchone()

    if not row:
        return 5.0, 0
    return float(row[0]), int(row[1])


async def create_ad(data, user_id: int, username: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO ads(
                user_id, username, kind, game, description,
                contact, payment, price, status,
                created_at, media_json
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
        cur = await db.execute(
            "SELECT * FROM ads WHERE id=?",
            (ad_id,),
        )
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
            """
            UPDATE ads
            SET status='published', published_message_id=?
            WHERE id=?
            """,
            (message_id, ad_id),
        )
        await db.commit()


def seller_label(ad) -> str:
    username = ad["username"].strip()
    if username:
        return f"@{username.lstrip('@')}"
    return "не указан"


def moderation_text(ad, media_count: int) -> str:
    rating, count = 5.0, 0
    # Рейтинг добавляется отдельным запросом перед вызовом этой функции.
    seller = seller_label(ad)

    return (
        f"🆕 <b>НОВАЯ ЗАЯВКА НА ПУБЛИКАЦИЮ #{ad['id']}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>ПРОДАВЕЦ:</b>\n"
        f"├ Юзернейм: {seller}\n"
        f"├ ID: <code>{ad['user_id']}</code>\n"
        f"└ Контакт: {escape(ad['contact'])}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>ИНФОРМАЦИЯ О ТОВАРЕ:</b>\n"
        f"├ Вид: {KIND_NAMES.get(ad['kind'], ad['kind'])}\n"
        f"├ Игра: {escape(ad['game'])}\n"
        f"└ Описание: {escape(ad['description'])}\n\n"
        f"💰 <b>ЦЕНА:</b> {ad['price']:.2f} ₽\n"
        f"💳 <b>Оплата:</b> {PAY_NAMES.get(ad['payment'], ad['payment'])}\n"
        f"📸 <b>Медиа:</b> {media_count}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Выберите действие:"
    )


def channel_post_text(ad, rating: float) -> str:
    kind = KIND_NAMES.get(ad["kind"], ad["kind"])
    emoji = KIND_EMOJI.get(ad["kind"], "📦")
    price = f"{ad['price']:.0f}₽" if float(ad["price"]).is_integer() else f"{ad['price']:.2f}₽"
    rating_text = f"{rating:.1f}".replace(".", ",")

    seller = seller_label(ad)

    return (
        f"📦<b>Товар #{ad['id']} — {escape(kind)} {emoji}</b>\n"
        f"🎮<b>Игра:</b> {escape(ad['game'])};\n"
        f"👑<b>Статус:</b> Не продан;\n"
        f"💰<b>Цена:</b> {price};\n"
        f"💳<b>Способ оплаты:</b> "
        f"{escape(PAY_NAMES.get(ad['payment'], ad['payment']))}.\n\n"
        f"👤<b>Продавец (SMDC {rating_text}/5):</b> {seller}\n\n"
        f"📖<b>Информация о товаре:</b> "
        f"{escape(ad['description'])}\n\n"
        f"🔎<b>Ссылка на пост:</b> SMDC."
    )


def make_post_link(channel: str, message_id: int) -> str | None:
    if PUBLIC_CHANNEL_URL:
        base = PUBLIC_CHANNEL_URL.rstrip("/")
        return f"{base}/{message_id}"

    if channel.startswith("@"):
        return f"https://t.me/{channel[1:]}/{message_id}"

    return None


async def send_channel_ad(ad):
    media = json.loads(ad["media_json"] or "[]")
    rating, _ = await get_user_rating(ad["user_id"])
    caption = channel_post_text(ad, rating)

    sent_message = None

    if media:
        first = media[0]
        if first["type"] == "photo":
            sent_message = await bot.send_photo(
                PUBLIC_CHANNEL,
                first["file_id"],
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
                await bot.send_photo(
                    PUBLIC_CHANNEL,
                    item["file_id"],
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


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await save_user(message.from_user)

    await message.answer(
        "🛒 <b>Super Mechs Market</b>\n\n"
        "Добро пожаловать!\n"
        "Здесь можно покупать и выставлять товары.",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "sell")
async def sell_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(SellForm.kind)

    await callback.message.edit_text(
        "🔥 <b>ВЫСТАВЛЕНИЕ ТОВАРА</b>\n\n"
        "⚠️ Объявление пройдёт модерацию.\n\n"
        "<b>Шаг 1 из 7</b>\n"
        "Выберите вид товара:",
        reply_markup=kind_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("kind:"))
async def sell_kind(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.split(":", 1)[1]
    await state.update_data(kind=kind)
    await state.set_state(SellForm.game)

    await callback.message.edit_text(
        f"✅ Вид товара: <b>{KIND_NAMES[kind]}</b>\n\n"
        "<b>Шаг 2 из 7</b>\n"
        "Укажите игру.\n\n"
        "Пример: <i>Super Mechs</i>",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(SellForm.game)
async def sell_game(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ Напишите название игры.")
        return

    await state.update_data(game=text)
    await state.set_state(SellForm.description)

    await message.answer(
        "✅ Игра сохранена.\n\n"
        "<b>Шаг 3 из 7</b>\n"
        "Введите описание товара.",
        reply_markup=cancel_kb(),
    )


@router.message(SellForm.description)
async def sell_description(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ Описание не может быть пустым.")
        return

    await state.update_data(description=text, media=[])
    await state.set_state(SellForm.media)

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
    F.content_type.in_({ContentType.PHOTO, ContentType.VIDEO}),
)
async def sell_media(message: Message, state: FSMContext):
    data = await state.get_data()
    media = data.get("media", [])

    if message.photo:
        media.append(
            {
                "type": "photo",
                "file_id": message.photo[-1].file_id,
            }
        )
    elif message.video:
        media.append(
            {
                "type": "video",
                "file_id": message.video.file_id,
            }
        )

    await state.update_data(media=media)

    await message.answer(
        f"📸 Медиафайл #{len(media)} добавлен.\n\n"
        "Отправьте следующий файл или нажмите /done."
    )


@router.message(SellForm.media, Command("done"))
async def sell_media_done(message: Message, state: FSMContext):
    data = await state.get_data()

    if not data.get("media"):
        await message.answer("⚠️ Добавьте хотя бы одно фото или видео.")
        return

    await state.set_state(SellForm.contact)

    await message.answer(
        "<b>Шаг 5 из 7</b>\n"
        "Введите контакт для связи.\n\n"
        "Например: @username",
        reply_markup=cancel_kb(),
    )


@router.message(SellForm.media)
async def sell_media_wrong(message: Message):
    await message.answer(
        "📸 Отправьте фото/видео или нажмите /done."
    )


@router.message(SellForm.contact)
async def sell_contact(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ Введите контакт.")
        return

    await state.update_data(contact=text)
    await state.set_state(SellForm.payment)

    await message.answer(
        "<b>Шаг 6 из 7</b>\n"
        "Выберите способ оплаты:",
        reply_markup=payment_kb(),
    )


@router.callback_query(SellForm.payment, F.data.startswith("pay:"))
async def sell_payment(callback: CallbackQuery, state: FSMContext):
    payment = callback.data.split(":", 1)[1]
    await state.update_data(payment=payment)
    await state.set_state(SellForm.price)

    await callback.message.edit_text(
        f"✅ Способ оплаты: <b>{PAY_NAMES[payment]}</b>\n\n"
        "<b>Шаг 7 из 7</b>\n"
        "Введите цену в рублях.\n\n"
        "Например: <code>357</code>",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(SellForm.price)
async def sell_price(message: Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").replace("₽", "").strip()

    try:
        price = float(raw)
        if price <= 0 or price > 10_000_000:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введите корректную цену, например <code>357</code>."
        )
        return

    data = await state.get_data()
    data["price"] = price

    ad_id = await create_ad(
        data,
        message.from_user.id,
        message.from_user.username,
    )
    ad = await get_ad(ad_id)

    media_count = len(data.get("media", []))
    text = moderation_text(ad, media_count)

    if not ADMIN_IDS:
        await set_status(ad_id, "error")
        await message.answer(
            "⚠️ Заявка создана, но ADMIN_IDS не настроен. "
            "Администраторы не получили заявку."
        )
        await state.clear()
        return

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                text,
                reply_markup=admin_kb(ad_id),
            )

            for item in data.get("media", []):
                if item["type"] == "photo":
                    await bot.send_photo(
                        admin_id,
                        item["file_id"],
                    )
                else:
                    await bot.send_video(
                        admin_id,
                        item["file_id"],
                    )
        except Exception:
            logging.exception(
                "Не удалось отправить заявку администратору %s",
                admin_id,
            )

    await state.clear()

    await message.answer(
        f"✅ <b>ЗАЯВКА #{ad_id} ОТПРАВЛЕНА НА МОДЕРАЦИЮ!</b>\n\n"
        "⏱ Ожидайте решения администратора.\n"
        "📋 Статус можно посмотреть в «Мои объявления».",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "cancel_sell")
async def cancel_sell(
    callback: CallbackQuery,
    state: FSMContext,
):
    await state.clear()
    await callback.message.edit_text(
        "❌ Выставление товара отменено.",
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    await save_user(callback.from_user)
    rating, rating_count = await get_user_rating(
        callback.from_user.id
    )

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM ads WHERE user_id=?",
            (callback.from_user.id,),
        )
        count = (await cur.fetchone())[0]

    rating_text = f"{rating:.1f}".replace(".", ",")

    await callback.message.edit_text(
        "👤 <b>МОЙ ПРОФИЛЬ</b>\n\n"
        f"ID: <code>{callback.from_user.id}</code>\n"
        f"Username: @{callback.from_user.username or 'не указан'}\n"
        f"⭐ Рейтинг SMDC: {rating_text}/5"
        + (f" ({rating_count} оценок)" if rating_count else "")
        + f"\n📦 Объявлений: {count}",
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "my_ads")
async def my_ads(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, kind, game, price, status
            FROM ads
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 20
            """,
            (callback.from_user.id,),
        )
        rows = await cur.fetchall()

    status_names = {
        "pending": "⏳ На модерации",
        "published": "✅ Опубликовано",
        "rejected": "❌ Отклонено",
        "error": "⚠️ Ошибка настройки",
    }

    if not rows:
        text = (
            "📋 <b>МОИ ОБЪЯВЛЕНИЯ</b>\n\n"
            "У вас пока нет объявлений."
        )
    else:
        parts = ["📋 <b>МОИ ОБЪЯВЛЕНИЯ</b>\n"]
        for row in rows:
            price = (
                f"{row['price']:.0f} ₽"
                if float(row["price"]).is_integer()
                else f"{row['price']:.2f} ₽"
            )
            parts.append(
                f"📦 <b>Товар #{row['id']}</b>\n"
                f"├ {KIND_NAMES.get(row['kind'], row['kind'])}\n"
                f"├ {escape(row['game'])}\n"
                f"├ {price}\n"
                f"└ {status_names.get(row['status'], row['status'])}\n"
            )
        text = "\n".join(parts)

    await callback.message.edit_text(
        text,
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "rules")
async def rules(callback: CallbackQuery):
    await callback.message.edit_text(
        "ℹ️ <b>ПРАВИЛА</b>\n\n"
        "1. Публикуйте только реальные объявления.\n"
        "2. Объявление проходит модерацию.\n"
        "3. Запрещённые товары и услуги не публикуются.\n"
        "4. Не отправляйте лишние персональные данные.\n"
        "5. Администрация может отклонить объявление.",
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    await callback.message.edit_text(
        "🆘 <b>ПОДДЕРЖКА</b>\n\n"
        "Контакт поддержки можно указать в настройках проекта.",
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "buy")
async def buy(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛍 <b>МАГАЗИН</b>\n\n"
        "Каталог товаров подключим следующим этапом.",
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("approve:"))
async def approve(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "⛔ У вас нет прав администратора.",
            show_alert=True,
        )
        return

    ad_id = int(callback.data.split(":", 1)[1])
    ad = await get_ad(ad_id)

    if not ad or ad["status"] != "pending":
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
        sent = await send_channel_ad(ad)
    except Exception as exc:
        logging.exception("Ошибка публикации объявления #%s", ad_id)
        await callback.answer(
            "Не удалось опубликовать. Проверьте права бота в канале.",
            show_alert=True,
        )
        return

    await set_published(ad_id, sent.message_id)

    link = make_post_link(
        PUBLIC_CHANNEL,
        sent.message_id,
    )

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    admin_result = f"✅ <b>Товар #{ad_id} опубликован в канале.</b>"
    if link:
        admin_result += f"\n🔎 <a href=\"{link}\">Открыть пост</a>"

    await callback.message.answer(admin_result)

    user_result = (
        f"✅ <b>Ваша заявка #{ad_id} одобрена "
        f"и опубликована!</b>"
    )
    if link:
        user_result += f"\n🔎 <a href=\"{link}\">Открыть объявление</a>"

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

    await callback.answer("Опубликовано!")


@router.callback_query(F.data.startswith("reject:"))
async def reject(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "⛔ У вас нет прав администратора.",
            show_alert=True,
        )
        return

    ad_id = int(callback.data.split(":", 1)[1])
    ad = await get_ad(ad_id)

    if not ad or ad["status"] != "pending":
        await callback.answer(
            "Заявка уже обработана.",
            show_alert=True,
        )
        return

    await set_status(ad_id, "rejected")

    await callback.message.edit_reply_markup(
        reply_markup=None
    )
    await callback.message.answer(
        f"❌ <b>Заявка #{ad_id} отклонена.</b>"
    )

    try:
        await bot.send_message(
            ad["user_id"],
            f"❌ <b>Ваша заявка #{ad_id} отклонена "
            f"модератором.</b>",
        )
    except Exception:
        logging.exception(
            "Не удалось уведомить продавца %s",
            ad["user_id"],
        )

    await callback.answer("Отклонено.")


@router.message(Command("myid"))
async def myid(message: Message):
    await message.answer(
        "🆔 <b>Ваш Telegram ID:</b>\n"
        f"<code>{message.from_user.id}</code>\n\n"
        "Добавьте этот номер в ADMIN_IDS в файле .env."
    )


@router.message(Command("sell"))
async def sell_command(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(SellForm.kind)
    await message.answer(
        "📦 Выберите вид товара:",
        reply_markup=kind_kb(),
    )


@router.message(Command("cancel"))
async def cancel_command(
    message: Message,
    state: FSMContext,
):
    await state.clear()
    await message.answer(
        "❌ Действие отменено.",
        reply_markup=main_menu(),
    )


async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    logging.info("Бот запущен.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
