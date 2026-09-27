import json
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

from config import ADMIN_IDS, PUBLIC_CHANNEL
from core.utils import channel_post_text, make_post_link
from core.watermark import process_photo_with_watermark
from db.ads import get_ad, set_published, set_status
from db.users import get_user_rating

router = Router()
bot_ref = None


def set_bot(bot):
    global bot_ref
    bot_ref = bot


async def send_channel_ad(ad):
    media = json.loads(ad["media_json"] or "[]")
    rating, _ = await get_user_rating(ad["user_id"])
    caption = channel_post_text(ad, rating)
    sent = None

    if media:
        first = media[0]
        if first["type"] == "photo":
            photo = await process_photo_with_watermark(bot_ref, first["file_id"])
            sent = await bot_ref.send_photo(PUBLIC_CHANNEL, photo, caption=caption)
        elif first["type"] == "video":
            sent = await bot_ref.send_video(PUBLIC_CHANNEL, first["file_id"], caption=caption)

        for item in media[1:]:
            if item["type"] == "photo":
                photo = await process_photo_with_watermark(bot_ref, item["file_id"])
                await bot_ref.send_photo(PUBLIC_CHANNEL, photo)
            elif item["type"] == "video":
                await bot_ref.send_video(PUBLIC_CHANNEL, item["file_id"])
    else:
        sent = await bot_ref.send_message(PUBLIC_CHANNEL, caption)

    return sent


@router.callback_query(F.data.startswith("approve:"))
async def approve(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ У вас нет прав администратора.", show_alert=True)
        return

    try:
        ad_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Ошибка заявки.", show_alert=True)
        return

    ad = await get_ad(ad_id)
    if not ad or ad["status"] != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    if not PUBLIC_CHANNEL:
        await callback.answer("PUBLIC_CHANNEL не настроен.", show_alert=True)
        return

    try:
        sent = await send_channel_ad(ad)
    except Exception:
        logging.exception("Ошибка публикации объявления #%s", ad_id)
        await callback.answer(
            "Не удалось опубликовать. Проверьте права бота в канале.",
            show_alert=True,
        )
        return

    if not sent:
        await callback.answer("Telegram не вернул сообщение публикации.", show_alert=True)
        return

    await set_published(ad_id, sent.message_id)
    link = make_post_link(PUBLIC_CHANNEL, sent.message_id)

    await callback.message.edit_reply_markup(reply_markup=None)

    admin_result = f"✅ <b>Товар #{ad_id} опубликован в канале.</b>"
    if link:
        admin_result += f'\n🔎 <a href="{link}">Открыть пост</a>'
    await callback.message.answer(admin_result)

    user_result = f"✅ <b>Ваша заявка #{ad_id} одобрена и опубликована!</b>"
    if link:
        user_result += f'\n🔎 <a href="{link}">Открыть объявление</a>'

    try:
        await bot_ref.send_message(ad["user_id"], user_result)
    except Exception:
        logging.exception("Не удалось уведомить продавца %s", ad["user_id"])

    await callback.answer("Опубликовано!")


@router.callback_query(F.data.startswith("reject:"))
async def reject(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ У вас нет прав администратора.", show_alert=True)
        return

    try:
        ad_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Ошибка заявки.", show_alert=True)
        return

    ad = await get_ad(ad_id)
    if not ad or ad["status"] != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    await set_status(ad_id, "rejected")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ <b>Заявка #{ad_id} отклонена.</b>")

    try:
        await bot_ref.send_message(
            ad["user_id"],
            f"❌ <b>Ваша заявка #{ad_id} отклонена модератором.</b>",
        )
    except Exception:
        logging.exception("Не удалось уведомить продавца %s", ad["user_id"])

    await callback.answer("Отклонено.")