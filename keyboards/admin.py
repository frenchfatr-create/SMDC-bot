from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def admin_kb(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{ad_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{ad_id}"),
        ],
        [InlineKeyboardButton(text="💰 Изменить цену", callback_data=f"price_edit:menu:{ad_id}")],
        [InlineKeyboardButton(text="🖼 Заменить главное фото", callback_data=f"replace_photo:{ad_id}")],
    ])


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Изменить рейтинг", callback_data="admin_rating")],
        [InlineKeyboardButton(text="🖼 Водяной знак", callback_data="admin_watermark")],
        [InlineKeyboardButton(text="📦 Управление товарами", callback_data="admin_products")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_menu")],
    ])


def watermark_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Установить водяной знак", callback_data="watermark_set")],
        [InlineKeyboardButton(text="🗑 Удалить водяной знак", callback_data="watermark_delete")],
        [InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_panel")],
    ])