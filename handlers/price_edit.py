import json
import logging
from html import escape

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS, PUBLIC_CHANNEL
from core.constants import KIND_NAMES, KIND_EMOJI, PAY_NAMES
from core.utils import format_price, rating_text, seller_label
from db.ads import get_ad, update_ad_price
from db.users import get_user_rating
from keyboards.common import main_menu
from states.forms import PriceEdit

router = Router()
bot_ref = None


def set_bot(bot):
    global bot_ref
    bot_ref = bot


def _cancel_kb(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"price_edit:cancel:{ad_id}")]
    ])


@router.callback_query(F.data.startswith("price_edit:menu:"))
async def price_edit_menu(callback: CallbackQuery):
    try:
        ad_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("Ошибка ID.", show_alert=True)
        return

    ad = await get_ad(ad_id)
    if not ad:
        await callback.answer("Товар не найден.", show_alert=True)
        return

    if callback.from_user.id not in ADMIN_IDS and callback.from_user.id != ad["user_id"]:
        await callback.answer("⛔ Нет прав.", show_alert=True)
        return

    await callback.message.answer(
        "💰 <b>ИЗМЕНЕНИЕ ЦЕНЫ</b>\n\n"
        f"Товар #{ad_id}\n"
        f"Текущая цена: <b>{format_price(ad['price'])}</b>\n\n"
        "Введите новую цену в рублях.\n"
        "Например: <code>4.5</code> или <code>5000</code>",
        reply_markup=_cancel_kb(ad_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("price_edit:cancel:"))
async def price_edit_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Изменение цены отменено.",
        reply_markup=main_menu(callback.from_user.id),
    )
    await callback.answer()


@router.message(PriceEdit.new_price)
async def price_edit_receive(message: Message, state: FSMContext):
    raw = (
        (message.text or "")
        .replace(",", ".")
        .replace("₽", "")
        .strip()
    )
    try:
        new_price = float(raw)
        if new_price <= 0 or new_price > 10_000_000:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректную цену, например <code>4.5</code>.")
        return

    data = await state.get_data()
    ad_id = int(data.get("ad_id", 0))
    await state.clear()

    ad = await get_ad(ad_id)
    if not ad:
        await message.answer("❌ Товар не найден.")
        return

    old_price = float(ad["price"])
    await update_ad_price(ad_id, new_price)

    post_updated = False
    if PUBLIC_CHANNEL and ad["status"] == "published" and ad["published_message_id"]:
        try:
            media = json.loads(ad["media_json"] or "[]")
            rating, _ = await get_user_rating(ad["user_id"])
            caption = _build_caption(ad, rating, new_price)

            if media:
                await bot_ref.edit_message_caption(
                    chat_id=PUBLIC_CHANNEL,
                    message_id=ad["published_message_id"],
                    caption=caption,
                )
            else:
                await bot_ref.edit_message_text(
                    chat_id=PUBLIC_CHANNEL,
                    message_id=ad["published_message_id"],
                    text=caption,
                )
            post_updated = True
        except Exception as e:
            logging.exception("Не удалось отредактировать пост #%s: %s", ad_id, e)

    if message.from_user.id in ADMIN_IDS and ad["user_id"] != message.from_user.id:
        try:
            await bot_ref.send_message(
                ad["user_id"],
                f"💰 <b>Цена товара #{ad_id} изменена администратором.</b>\n\n"
                f"Было: {format_price(old_price)}\n"
                f"Стало: {format_price(new_price)}",
            )
        except Exception:
            pass

    if message.from_user.id not in ADMIN_IDS:
        for admin_id in ADMIN_IDS:
            try:
                await bot_ref.send_message(
                    admin_id,
                    f"💰 <b>Продавец изменил цену товара #{ad_id}</b>\n\n"
                    f"Было: {format_price(old_price)}\n"
                    f"Стало: {format_price(new_price)}\n"
                    f"Продавец: {escape(seller_label(ad))}",
                )
            except Exception:
                pass

    await message.answer(
        f"✅ <b>Цена обновлена</b>\n\n"
        f"Товар #{ad_id}\n"
        f"Было: {format_price(old_price)}\n"
        f"Стало: <b>{format_price(new_price)}</b>\n"
        + ("\n🔎 Пост в канале отредактирован." if post_updated else ""),
        reply_markup=main_menu(message.from_user.id),
    )


def _build_caption(ad, rating: float, new_price: float) -> str:
    kind = KIND_NAMES.get(ad["kind"], ad["kind"])
    emoji = KIND_EMOJI.get(ad["kind"], "📦")
    seller = seller_label(ad)
    return (
        f"📦<b>Товар #{ad['id']} — {escape(kind)} {emoji}</b>\n"
        f"🎮<b>Игра:</b> {escape(ad['game'])};\n"
        f"👑<b>Статус:</b> Не продан;\n"
        f"💰<b>Цена:</b> {format_price(new_price)};\n"
        f"💳<b>Способ оплаты:</b> "
        f"{escape(PAY_NAMES.get(ad['payment'], ad['payment']))}.\n\n"
        f"👤<b>Продавец (SMDC {rating_text(rating)}/5):</b> "
        f"{escape(seller)}\n\n"
        f"📖<b>Информация о товаре:</b> "
        f"{escape(ad['description'])}\n\n"
        f"🔎<b>Ссылка на пост:</b> "
        f'<a href="https://t.me/smdcshop">SMDC</a>.'
    )