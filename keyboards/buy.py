from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import ADMIN_IDS
from core.constants import KIND_NAMES
from core.utils import format_price


def buy_categories_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Все товары", callback_data="buy:cat:all")],
        [
            InlineKeyboardButton(text="🪪 Аккаунты", callback_data="buy:cat:account"),
            InlineKeyboardButton(text="🪙 Валюта", callback_data="buy:cat:currency"),
        ],
        [
            InlineKeyboardButton(text="🛠 Услуги", callback_data="buy:cat:service"),
            InlineKeyboardButton(text="📦 Другое", callback_data="buy:cat:other"),
        ],
        [InlineKeyboardButton(text="🔎 Поиск", callback_data="buy:search")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_menu")],
    ])


def product_list_kb(ads) -> InlineKeyboardMarkup:
    rows = []
    for ad in ads:
        kind = KIND_NAMES.get(ad["kind"], ad["kind"])
        price = format_price(ad["price"])
        rows.append([
            InlineKeyboardButton(
                text=f"#{ad['id']} • {kind} • {price}",
                callback_data=f"product:{ad['id']}",
            )
        ])
    rows.append([
        InlineKeyboardButton(text="🔎 Поиск", callback_data="buy:search"),
        InlineKeyboardButton(text="📂 Категории", callback_data="buy"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_kb(ad_id: int, seller_id: int, viewer_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="👤 Связаться с продавцом", callback_data=f"contact:{ad_id}")],
        [InlineKeyboardButton(text="💰 Изменить цену", callback_data=f"price_edit:menu:{ad_id}")],
        [InlineKeyboardButton(text="🔙 Назад в каталог", callback_data="buy")],
    ]
    if viewer_id == seller_id or viewer_id in ADMIN_IDS:
        rows.insert(1, [
            InlineKeyboardButton(text="💰 Отметить проданным", callback_data=f"mark_sold:{ad_id}")
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)