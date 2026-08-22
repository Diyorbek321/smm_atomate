#!/usr/bin/env python
"""Seed a demo education centre so the system is usable in one command.

    python scripts/seed.py [--telegram-user-id 123456789]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.models.enums import AdminRole, BusinessCategory, Language, ToneOfVoice  # noqa: E402
from app.repositories.business import (  # noqa: E402
    AdminRepository,
    BusinessRepository,
    KnowledgeBaseRepository,
)

log = get_logger(__name__)

DEMO = {
    "name": "Bright IELTS Academy",
    "category": BusinessCategory.EDUCATION,
    "tone_of_voice": ToneOfVoice.CASUAL,
    "target_audience": "18-30 yoshdagi talabalar va ishlayotgan yoshlar, IELTS 6.5+ olmoqchi",
    "language": Language.UZ,
    "timezone": "Asia/Tashkent",
    "settings": {"posts_per_week": 10, "posting_hours": [9, 13, 18], "auto_approve": False},
}

KNOWLEDGE = {
    "key_offerings": [
        {"name": "IELTS Intensiv", "description": "3 oylik jadal tayyorgarlik", "duration": "3 oy", "level": "B1+"},
        {"name": "General English", "description": "Noldan boshlovchilar uchun", "duration": "6 oy", "level": "A1"},
        {"name": "Speaking Club", "description": "Haftada 2 marta jonli muloqot", "duration": "doimiy"},
    ],
    "prices": [
        {"item": "IELTS Intensiv", "price": 600000, "currency": "UZS", "note": "oyiga"},
        {"item": "General English", "price": 450000, "currency": "UZS", "note": "oyiga"},
        {"item": "Speaking Club", "price": 200000, "currency": "UZS", "note": "oyiga"},
    ],
    "usps": [
        "O'qituvchilarning barchasi 7.5+ IELTS ballga ega",
        "Guruhda maksimal 8 kishi",
        "Har hafta mock test va shaxsiy tahlil",
        "Natija bo'lmasa — keyingi kurs bepul",
    ],
    "teacher_profiles": [
        {"name": "Aziz Rahimov", "role": "IELTS instructor", "achievements": "IELTS 8.0", "experience_years": 6},
        {"name": "Malika Yusupova", "role": "Speaking coach", "achievements": "IELTS 7.5", "experience_years": 4},
    ],
    "faq": [
        {"q": "Darslar qachon bo'ladi?", "a": "Har kuni 3 ta vaqt: 9:00, 14:00 va 18:00"},
        {"q": "Sinov darsi bormi?", "a": "Ha, birinchi dars mutlaqo bepul"},
        {"q": "To'lov qanday?", "a": "Naqd, plastik karta yoki Payme/Click orqali"},
    ],
    "success_stories": [
        {"name": "Dilnoza", "result": "IELTS 7.5", "quote": "3 oyda 5.5 dan 7.5 ga chiqdim"},
        {"name": "Javohir", "result": "IELTS 7.0", "quote": "Speaking'dan qo'rquvim yo'qoldi"},
    ],
    "raw_notes": (
        "Markaz 2019 yilda ochilgan. Chilonzor va Yunusobodda 2 ta filial bor. "
        "500 dan ortiq bitiruvchi. Sentyabrda yangi guruhlar ochiladi."
    ),
    "phone": "+998 90 123 45 67",
    "telegram_username": "bright_ielts",
    "instagram_username": "bright.ielts",
    "address": "Toshkent, Chilonzor 9-kvartal",
    "working_hours": "Du-Sh 09:00-20:00",
    "brand_colors": {"accent": "#FF6B35", "bg": "#0B0D12", "text": "#F5F7FA"},
    "preferred_hashtags": ["#ielts", "#toshkent", "#brightielts", "#ingliztili"],
    "banned_topics": ["siyosat", "din"],
}


async def seed(telegram_user_id: int | None) -> None:
    async with session_scope() as session:
        businesses = BusinessRepository(session)

        existing = await businesses.by_slug("bright-ielts-academy")
        if existing is not None:
            log.info("seed_skipped_already_exists", business=str(existing.id))
            print(f"Business already exists: {existing.id}")
            return

        business = await businesses.create_with_defaults(slug="bright-ielts-academy", **DEMO)

        knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)
        for field, value in KNOWLEDGE.items():
            setattr(knowledge, field, value)
        knowledge.compute_completeness()

        if telegram_user_id:
            await AdminRepository(session).upsert(
                business.id,
                telegram_user_id,
                full_name="Demo Owner",
                role=AdminRole.OWNER,
                receives_reviews=True,
            )

        await session.flush()
        print(f"✅ Seeded '{business.name}'")
        print(f"   business_id : {business.id}")
        print(f"   completeness: {knowledge.completeness_score:.0%}")
        if telegram_user_id:
            print(f"   admin       : telegram user {telegram_user_id}")
        print("\nNext: POST /api/v1/generate/plan with this business_id, or /plan in the bot.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data")
    parser.add_argument(
        "--telegram-user-id",
        type=int,
        default=None,
        help="Telegram user id to register as the reviewing owner",
    )
    args = parser.parse_args()

    configure_logging("seed")
    asyncio.run(seed(args.telegram_user_id))


if __name__ == "__main__":
    main()
