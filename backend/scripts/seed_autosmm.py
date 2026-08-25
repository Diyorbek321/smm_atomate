#!/usr/bin/env python
"""Register Postchi as a business inside its own platform.

    Postchi — ommaviy brend nomi. Kod va omborda nom o'zgarmaydi
    (AutoSMM AI / smm_atomate); o'zgargani mijoz ko'radigan qism.

    python scripts/seed_autosmm.py [--telegram-user-id 123456789]

The product runs its own channel. That is not a demo — it is the strongest
claim available: a system that cannot keep its own feed alive has no business
selling that service, and the failure would be public within a week.

Everything below that could be derived from the codebase is filled in and
correct. Everything marked TODO is a decision only the owner can make; the
script refuses to run while any of them is unanswered rather than seeding a
channel that announces a placeholder phone number to the world.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope
from app.models.enums import (
    AdminRole,
    BusinessCategory,
    Language,
    Plan,
    ToneOfVoice,
)
from app.repositories.business import (
    AdminRepository,
    BusinessRepository,
    KnowledgeBaseRepository,
)

log = get_logger(__name__)

SLUG = "postchi"

#: Anything still equal to this blocks the seed. Better an error than a post.
TODO = "TODO"

BUSINESS = {
    "name": "Postchi",
    "category": BusinessCategory.TECH,
    "tone_of_voice": ToneOfVoice.EXPERT,
    "target_audience": (
        "Mahalliy biznes egalari — o'quv markaz, restoran va kafe, do'kon va onlayn "
        "savdo, go'zallik saloni, klinika, ko'chmas mulk agentligi, xizmat ko'rsatuvchi "
        "kompaniyalar. Toshkent va viloyat shaharlari, 1-3 filial. SMM'ni o'zi yoki "
        "bitta freelancer bilan yuritadi, natijani o'lchay olmaydi."
    ),
    "language": Language.UZ,
    "timezone": "Asia/Tashkent",
    # Pro on purpose: the product must run itself on the tier it sells hardest,
    # including the real-photo preference and the clip engine.
    "plan": Plan.PRO,
    "settings": {
        "posts_per_week": 5,
        "posting_hours": [10, 19],
        # Never on. The whole positioning is that a human sees every post
        # before a follower does; auto-approving our own feed would contradict
        # the thing we charge for.
        "auto_approve": False,
    },
}

KNOWLEDGE = {
    # ---- what we sell ------------------------------------------------- #
    "key_offerings": [
        {
            "name": "START",
            "description": (
                "Telegram uchun oyiga 16 ta post. Matn, karta, so'rovnoma. "
                "Brend ranglari asosida. Reels va montaj yo'q."
            ),
            "duration": "oylik",
        },
        {
            "name": "STANDARD",
            "description": (
                "Telegram va Instagram uchun oyiga 28 ta post: feed, karusel, story. "
                "Oyiga 4 ta reels va 4 ta video montaj — mijoz kadridan."
            ),
            "duration": "oylik",
        },
        {
            "name": "PRO",
            "description": (
                "Oyiga 48 ta post, 12 reels, 12 video montaj, uzun videodan klip, "
                "lid avtojavobi. Haqiqiy foto generatsiyadan ustun turadi. "
                "Javob vaqti 8 soat."
            ),
            "duration": "oylik",
        },
    ],
    # Uchala narx ochiq. So'mda, chunki reklama matni o'zbekcha va mijoz
    # so'mda o'ylaydi — `facts.py` UZS ni «3 190 000 so'm» ko'rinishida yozadi.
    # Zina 1 : 2.4 : 4.6 — o'rtadagisi eng foydali ko'rinsin uchun.
    "prices": [
        {"item": "START", "price": 690000, "currency": "UZS", "note": "oyiga"},
        {"item": "STANDARD", "price": 1690000, "currency": "UZS", "note": "oyiga"},
        {"item": "PRO", "price": 3190000, "currency": "UZS", "note": "oyiga"},
    ],
    # ---- why us, in checkable form ------------------------------------ #
    # Every line here is a fact the code enforces, not a claim. That is the
    # point: the product's own copy has to survive its own fact gate.
    "usps": [
        "Faktsiz post chiqmaydi — tizim narx, sana yoki raqam bo'lmagan matnni o'zi rad etadi",
        "«Sifatli ta'lim», «malakali ustozlar» kabi 49 ta bo'sh ibora taqiqlangan ro'yxatda",
        "Bitta xom videodan 5 ta short — 2 daqiqada, brend ranglari bilan",
        "Har oy suratga olish brifi: 14 tagacha aniq kadr, qanday olish yo'riqnomasi bilan",
        "Kadr ro'yxati soha bo'yicha — restoranga bug' va tortish, klinikaga sterilizatsiya, "
        "salonga oldin/keyin",
        "So'nggi 30 kun tekshiriladi — o'xshash post ikkinchi marta chiqmaydi",
        "Oylik hisobot lid soni bilan, ko'rish soni bilan emas",
        "Har post Telegramda tasdiqdan o'tadi — hech narsa so'ramasdan chiqmaydi",
    ],
    # ---- questions people actually ask -------------------------------- #
    "faq": [
        {
            "q": "AI yozgani bilinib qolmaydimi?",
            "a": (
                "Bilinadigan qismi — bo'sh sifatlar va faktsiz gaplar. Tizim ikkalasini "
                "ham darvozada to'xtatadi: har postda tekshirsa bo'ladigan raqam, sana "
                "yoki ism bo'lishi shart."
            ),
        },
        {
            "q": "Faqat o'quv markazlar uchunmi?",
            "a": (
                "Yo'q. Restoran, do'kon, salon, klinika, ko'chmas mulk va xizmat "
                "biznesi uchun ham ishlaydi. Har sohaga o'z kadr ro'yxati va o'z "
                "mavsumiy rejasi bor."
            ),
        },
        {
            "q": "Mening videom kerakmi?",
            "a": (
                "Reels uchun ha. Har oy boshida 14 tagacha kadr ro'yxati yuboriladi — "
                "telefon yetarli, 20 daqiqa vaqt oladi. Kadr bo'lmasa matnli karta chiqadi."
            ),
        },
        {
            "q": "Rasmlar generatsiya qilinadimi?",
            "a": (
                "PRO tarifda biznesingizning haqiqiy surati birinchi o'rinda turadi. "
                "Generatsiya faqat haqiqiy foto yo'q joyda ishlatiladi."
            ),
        },
        {
            "q": "Postni o'zim ko'rib chiqamanmi?",
            "a": (
                "Ha, har biri Telegramga keladi. Tasdiqlash, tahrirlash yoki bekor "
                "qilish tugmalari bilan. Ovozli xabar bilan ham tuzatish mumkin — "
                "«Dushanbadagi narxni 400 mingga o'zgartir» deb aytsangiz kifoya."
            ),
        },
        {
            "q": "Instagramga ham chiqadimi?",
            "a": "STANDARD va PRO tariflarda ha. START faqat Telegram.",
        },
        {
            "q": "Qancha vaqtda boshlanadi?",
            "a": (
                "Bilim bazasini to'ldirish 20-30 daqiqa — botda savol-javob, ovozli "
                "javob ham bo'ladi. Birinchi haftalik reja o'sha kuni tayyor."
            ),
        },
    ],
    # ---- proof --------------------------------------------------------- #
    # Shanghai School is the pilot: the owner works there, and the first five
    # shorts were cut from their footage. Kept as a story rather than a claim
    # until the numbers from the first month exist.
    "success_stories": [
        {
            "name": "Shanghai School (Angren)",
            "result": "1 ta xom videodan 5 ta short",
            "quote": (
                "73 soniyalik promo videodan 5 xil shablonda 5 ta reels chiqdi — "
                "brend ranglari, manba ovozi va matn qatlami bilan, 10 daqiqada."
            ),
        },
    ],
    "teacher_profiles": [],
    # ---- positioning, for the model to read --------------------------- #
    "raw_notes": (
        "Postchi — mahalliy biznes uchun avtonom SMM tizimi: o'quv markaz, restoran, "
        "do'kon, salon, klinika, ko'chmas mulk. Nom «post qiluvchi» "
        "degani, pochtachi kabi yasalgan: mahsulot o'zini xodim deb ko'rsatadi. Farqi: kontent "
        "generatsiyasi emas, sifat darvozasi. Har post faktga tekshiriladi, bo'sh "
        "iboralar ro'yxati bo'yicha filtrlanadi va so'nggi 30 kunlik postlar bilan "
        "solishtiriladi. Har oy mijozga suratga olish brifi boradi, oy oxirida lid "
        "soni bilan hisobot qaytadi. Suratga olish brifi har soha uchun alohida — "
        "restoranga bug' va tortish kadri, klinikaga sterilizatsiya, salonga oldin/keyin. "
        "@postchi kanalini tizimning o'zi yuritadi — har post "
        "ostida qancha vaqt ketgani va nima xato bo'lgani yoziladi. Birinchi pilot: "
        "Shanghai School, Angren — ta'lim sohasi."
    ),
    # ---- contact and brand — the owner's to fill ---------------------- #
    # Bu maydon texnik emas — CTA. `contact_line` shundan quriladi va har
    # post oxiriga, har kartaga va har reels ustiga tushadi. Shuning uchun
    # kanal emas, YOZIB BO'LADIGAN manzil: bot.
    "phone": "+998 93 191 33 08",
    "telegram_username": "inovatex",
    "instagram_username": "postchi.ai",
    "website": None,
    "address": None,
    "working_hours": "Du-Ju 09:00-19:00",
    # Chuqur ko'k maydon, bitta sariq urg'u, oq matn. Kalitlar renderer'ning
    # DEFAULT_COLORS iga mos — boshqasi jimgina tashlab yuboriladi.
    # To'liq qoidalar: promo/brand/postchi/brandbook.json
    "brand_colors": {
        "bg": "#0F2B63",
        "surface": "#081A3F",
        "text": "#FFFFFF",
        "primary": "#7FB0FF",
        "accent": "#FFCE1B",
        "on_accent": "#0F2B63",
    },
    # Rangdan tashqari hamma narsa: shrift, ovoz, taqiqlangan so'zlar.
    # To'liq qoidalar: promo/brand/postchi/brandbook.json
    "brand_kit": {
        "typography": {"display": "Anton", "body": "Inter"},
        "voice": {
            "summary": "Muhandis gapiradi: aniq, kamgap, raqam bilan. Sotuvchi emas.",
            "do": [
                "Raqam bilan gapir: «2 daqiqada render», «49 ta bo'sh ibora ro'yxatda».",
                "Kamchilikni ochiq ayt — nima ishlamasligini aytish qolganini ishonarli qiladi.",
                "Qisqa gap. Bir gapda bitta fikr.",
                "Mexanizmni ko'rsat, natijani va'da qilma.",
            ],
            "dont": [
                "Undov belgisi bilan hayajon yasama.",
                "Raqobatchini nomlab tanqid qilma.",
                "Obunachi soni va'da qilma — u bizga bog'liq emas.",
            ],
            "banned_words": [
                "inqilobiy",
                "zamonaviy yechim",
                "kelajak texnologiyasi",
                "sun'iy intellekt kuchi",
                "raqamli transformatsiya",
            ],
        },
        "logo_on_dark": "brand/postchi/mark-yellow.svg",
        "logo_on_light": "brand/postchi/mark-blue.svg",
    },
    # StyleDNA — har rasm promptiga qo'shiladi.
    "visual_style": {
        "palette": "deep navy field, one saturated yellow accent, white type",
        "lighting": "hard directional light, deep shadows, no soft glow",
        "lens": "35mm, straight on, minimal depth of field",
        "grade": "high contrast, cool navy cast, visible grain",
        "subject": (
            "screens, interfaces, hands on a keyboard, real workspaces — "
            "no stock smiles, no robots, no glowing brains"
        ),
    },
    "preferred_hashtags": [
        "#postchi",
        "#smmuz",
        "#oquvmarkaz",
        "#telegramsmm",
    ],
    "banned_topics": ["siyosat", "din"],
    "competitors": [],                # TODO: mahalliy raqobatchilar, agar bilsangiz
}


def _unresolved() -> list[str]:
    """Every TODO still standing, so the script can refuse with a list."""
    gaps: list[str] = []
    if not KNOWLEDGE["prices"]:
        gaps.append("prices — tariflar narxi")
    for field in ("phone", "telegram_username", "instagram_username"):
        if KNOWLEDGE[field] == TODO:
            gaps.append(f"{field}")
    if KNOWLEDGE["brand_colors"].get("accent") == TODO:
        gaps.append("brand_colors.accent — brend rangi")
    return gaps


async def seed(telegram_user_id: int | None, *, force: bool) -> None:
    gaps = _unresolved()
    if gaps and not force:
        print("❌ Quyidagilar hali to'ldirilmagan:\n")
        for gap in gaps:
            print(f"   • {gap}")
        print(
            "\nUlarni scripts/seed_autosmm.py ichida to'ldiring.\n"
            "Sinov uchun shundayligicha yuklamoqchi bo'lsangiz: --force"
        )
        raise SystemExit(1)

    async with session_scope() as session:
        businesses = BusinessRepository(session)

        existing = await businesses.by_slug(SLUG)
        if existing is not None:
            print(f"Postchi allaqachon mavjud: {existing.id}")
            return

        business = await businesses.create_with_defaults(slug=SLUG, **BUSINESS)

        knowledge = await KnowledgeBaseRepository(session).get_or_create(business.id)
        for field, value in KNOWLEDGE.items():
            setattr(knowledge, field, None if value == TODO else value)
        knowledge.compute_completeness()

        if telegram_user_id:
            await AdminRepository(session).upsert(
                business.id,
                telegram_user_id,
                full_name="Diyorbek",
                role=AdminRole.OWNER,
                receives_reviews=True,
            )

        await session.flush()
        print(f"✅ '{business.name}' qo'shildi")
        print(f"   business_id : {business.id}")
        print(f"   tarif       : {business.plan}")
        print(f"   to'liqligi  : {knowledge.completeness_score:.0%}")
        if knowledge.missing_fields:
            print(f"   yetishmaydi : {', '.join(knowledge.missing_fields)}")
        if telegram_user_id:
            print(f"   admin       : telegram {telegram_user_id}")
        print("\nKeyingi qadam: botda /plan — birinchi haftalik reja.")
        print("                botda /brif — shu oyning suratga olish brifi.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Postchi ni o'z tizimiga biznes sifatida qo'shish")
    parser.add_argument("--telegram-user-id", type=int, default=None,
                        help="Postlarni tasdiqlaydigan Telegram foydalanuvchi id")
    parser.add_argument("--force", action="store_true",
                        help="To'ldirilmagan maydonlar bilan ham yuklash (faqat sinov uchun)")
    args = parser.parse_args()

    configure_logging("seed-autosmm")
    asyncio.run(seed(args.telegram_user_id, force=args.force))


if __name__ == "__main__":
    main()
