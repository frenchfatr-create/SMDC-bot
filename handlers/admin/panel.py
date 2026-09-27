from aiogram import Router, F
from aiogram.types import CallbackQuery

from config import ADMIN_IDS
from db.settings import get_setting
from keyboards.admin import admin_panel_kb

router = Router()


@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет прав администратора.", show_alert=True)
        return

    watermark = await get_setting("watermark_file_id", "")
    status = "установлен" if watermark else "не установлен"

    await callback.message.edit_text(
        "⚙️ <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        f"🖼 Водяной знак: <b>{status}</b>\n\n"
        "Здесь можно управлять рейтингами, водяным знаком и товарами.",
        reply_markup=admin_panel_kb(),
    )
    await callback.answer()