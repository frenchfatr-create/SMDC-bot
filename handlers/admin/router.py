from aiogram import Router
from . import panel, rating, watermark, replace_photo, products, moderation

router = Router()
router.include_router(panel.router)
router.include_router(rating.router)
router.include_router(watermark.router)
router.include_router(replace_photo.router)
router.include_router(products.router)
router.include_router(moderation.router)