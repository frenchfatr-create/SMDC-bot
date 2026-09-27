from html import escape
from config import PUBLIC_CHANNEL_URL, PUBLIC_CHANNEL
from core.constants import KIND_NAMES, KIND_EMOJI, PAY_NAMES


def format_price(price) -> str:
    value = float(price)
    if value.is_integer():
        return f"{value:.0f} ₽"
    return f"{value:.2f} ₽"


def rating_text(rating: float) -> str:
    return f"{rating:.1f}".replace(".", ",")


def seller_label(ad) -> str:
    username = (ad["username"] or "").strip()
    if username:
        return "@" + username.lstrip("@")
    return "не указан"


def make_post_link(channel: str, message_id: int) -> str | None:
    if PUBLIC_CHANNEL_URL:
        base = PUBLIC_CHANNEL_URL.rstrip("/")
        return f"{base}/{message_id}"
    if channel.startswith("@"):
        return f"https://t.me/{channel[1:]}/{message_id}"
    return None


def moderation_text(ad, media_count: int) -> str:
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
        f"├ Вид: {escape(KIND_NAMES.get(ad['kind'], ad['kind']))}\n"
        f"├ Игра: {escape(ad['game'])}\n"
        f"└ Описание: {escape(ad['description'])}\n\n"
        f"💰 <b>ЦЕНА:</b> {format_price(ad['price'])}\n"
        f"💳 <b>Оплата:</b> "
        f"{escape(PAY_NAMES.get(ad['payment'], ad['payment']))}\n"
        f"📸 <b>Медиа:</b> {media_count}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Выберите действие:"
    )


def channel_post_text(ad, rating: float) -> str:
    kind = KIND_NAMES.get(ad["kind"], ad["kind"])
    emoji = KIND_EMOJI.get(ad["kind"], "📦")
    price = format_price(ad["price"])
    seller = seller_label(ad)

    return (
        f"📦<b>Товар #{ad['id']} — {escape(kind)} {emoji}</b>\n"
        f"🎮<b>Игра:</b> {escape(ad['game'])};\n"
        f"👑<b>Статус:</b> Не продан;\n"
        f"💰<b>Цена:</b> {price};\n"
        f"💳<b>Способ оплаты:</b> "
        f"{escape(PAY_NAMES.get(ad['payment'], ad['payment']))}.\n\n"
        f"👤<b>Продавец (SMDC {rating_text(rating)}/5):</b> "
        f"{escape(seller)}\n\n"
        f"📖<b>Информация о товаре:</b> "
        f"{escape(ad['description'])}\n\n"
        f"🔎<b>Ссылка на пост:</b> "
        f'<a href="https://t.me/smdcshop">SMDC</a>.'
    )