"""All user-facing bot copy (Uzbek) in one module."""

from __future__ import annotations

from app.models.enums import ContentItemStatus, ContentPillar, ContentType

START_NEW_USER = (
    "👋 Assalomu alaykum!\n\n"
    "Men <b>AutoSMM AI</b> — sizning avtomatik SMM xodimingizman.\n\n"
    "Men nima qila olaman:\n"
    "• Haftalik kontent rejasini tuzaman\n"
    "• Post matni va rasmini tayyorlayman\n"
    "• Siz tasdiqlaganingizdan keyin Telegram va Instagramga o'zim joylayman\n\n"
    "Boshlash uchun biznesingiz nomini yozing 👇"
)

START_KNOWN_USER = (
    "👋 Xush kelibsiz, <b>{name}</b>!\n\n"
    "Biznes: <b>{business}</b>\n"
    "Bilim bazasi: {progress}\n\n"
    "Nima qilamiz?"
)

NOT_REGISTERED = (
    "🔒 Siz hali hech qaysi biznesga biriktirilmagansiz.\n\n"
    "Admin sizni qo'shishi kerak yoki /start bosib yangi biznes yarating."
)

HELP = (
    "<b>AutoSMM AI — buyruqlar</b>\n\n"
    "/start — boshlash\n"
    "/plan — haftalik reja yaratish\n"
    "/review — tasdiqlanmagan postlar\n"
    "/quick — bitta tezkor post\n"
    "/kb — bilim bazasi holati\n"
    "/status — statistika\n"
    "/cancel — joriy amalni bekor qilish\n\n"
    "💡 Postni tahrirlash uchun <b>✏️ Tahrirlash</b> tugmasini bosing va\n"
    "ovozli xabar yuboring — masalan: <i>«Dushanbadagi narxni 400 ming qil»</i>."
)

ONBOARDING_INTRO = (
    "🧠 <b>Bilim bazasini to'ldiramiz</b>\n\n"
    "Men bir nechta savol beraman. Yozib ham, ovozli xabar bilan ham javob berishingiz mumkin.\n"
    "Qanchalik ko'p ma'lumot bersangiz, postlar shunchalik aniq chiqadi.\n\n"
    "<b>Savol 1:</b> {question}"
)

ONBOARDING_NEXT = "✅ {summary}\n\n📊 To'ldirilgani: {progress}\n\n<b>Keyingi savol:</b> {question}"

ONBOARDING_DONE = (
    "🎉 <b>Bilim bazasi tayyor!</b> ({progress})\n\n"
    "Endi /plan buyrug'i bilan haftalik reja yaratishingiz mumkin."
)

ONBOARDING_SAVED = "✅ Saqladim. {summary}\n\n📊 To'ldirilgani: {progress}"

DOCUMENT_PROCESSING = "📄 Hujjatni o'qiyapman, biroz kuting…"

DOCUMENT_UNSUPPORTED = "❌ Faqat PDF hujjatlarni qabul qilaman. PDF yuboring."

DOCUMENT_TOO_LARGE = "❌ Hujjat juda katta — 12 MB dan kichik PDF yuboring."

# --- video editor --------------------------------------------------------
VIDEO_RECEIVED = "🎬 Video qabul qilindi, yuklab olyapman…"
VIDEO_EDITING = (
    "✂️ <b>Tahrirlanyapti…</b>\n\n"
    "Jimliklar kesiladi, 9:16 ga moslanadi, ovoz tozalanadi, subtitr qo'yiladi, "
    "musiqa va brend kadrlari qo'shiladi.\n\n"
    "Tayyor bo'lgach tasdiqlash kartasi bo'lib keladi — odatda videoning uzunligicha vaqt oladi."
)
VIDEO_DONE = "✅ Video tayyor — tasdiqlash uchun yubordim."
VIDEO_TOO_LARGE = (
    "❌ Video juda katta — {limit} MB dan kichik bo'lishi kerak.\n\n"
    "Telegram'da <b>video sifatida</b> yuboring (fayl sifatida emas) — u avtomatik siqiladi."
)
VIDEO_TOO_LONG = "❌ Video juda uzun — {minutes} daqiqadan qisqa bo'lishi kerak."
VIDEO_DOWNLOAD_FAILED = "❌ Videoni yuklab bo'lmadi. Qaytadan yuborib ko'ring."
VIDEO_PLAN_REQUIRED = (
    "🔒 Video tahrirlash <b>Standard</b> va <b>Pro</b> tariflarida mavjud.\n\n"
    "Hozirgi tarifingizda bu xizmat yo'q — tarifni ko'tarish uchun bog'laning."
)

LEAD_WELCOME = (
    "Assalomu alaykum! 👋 {business} ga xush kelibsiz.\n\n"
    "Qaysi yo'nalish sizni qiziqtiradi? Yozib yuboring — "
    "masalan: ingliz tili, matematika, IT yoki boshqasi."
)

LEAD_ASK_PHONE = (
    "Rahmat! 📞 Menejerimiz siz bilan bog'lanishi uchun telefon raqamingizni "
    "qoldiring — pastdagi tugmani bosing yoki raqamni yozib yuboring."
)

LEAD_PHONE_BUTTON = "📞 Raqamni yuborish"
LEAD_SKIP_BUTTON = "O'tkazib yuborish"

LEAD_THANKS = (
    "✅ Rahmat! So'rovingiz qabul qilindi.\n\n"
    "Menejerimiz tez orada siz bilan bog'lanadi. "
    "Savollaringiz bo'lsa, shu yerga yozib qoldiring."
)

LEAD_NOTIFY = (
    "🔥 <b>Yangi lead!</b>\n\n"
    "👤 {name} {username}\n"
    "📞 {phone}\n"
    "💬 Qiziqishi: {interest}\n\n"
    "Tezroq bog'laning — issiq lead sovib qoladi."
)

PLAN_GENERATING = (
    "⏳ Reja tayyorlanmoqda…\n\n"
    "Har bir post 4 ta agentdan o'tadi (strateg → kopirayter → dizayn → muharrir), "
    "shuning uchun bir necha daqiqa ketadi. Tayyor bo'lgach postlarni shu yerga yuboraman — "
    "kutib o'tirishingiz shart emas."
)

PLAN_READY = (
    "📅 <b>{title}</b>\n\n"
    "Mavzu: {theme}\n"
    "Postlar soni: <b>{count}</b>\n"
    "Taqsimot: {distribution}\n"
    "O'rtacha sifat: <b>{quality}/10</b>\n\n"
    "Har bir postni alohida ko'rib chiqing yoki hammasini birdan tasdiqlang 👇"
)

PLAN_FAILED = "❌ Reja yaratishda xatolik: {error}"

NO_PENDING = "✅ Ko'rib chiqilmagan post yo'q. Hammasi tartibda!"

REVIEW_HEADER = (
    "{emoji} <b>{title}</b>\n"
    "├ Format: {content_type}\n"
    "├ Ustun: {pillar}\n"
    "├ Vaqt: <b>{scheduled}</b>\n"
    "└ Sifat: {quality}/10 {quality_bar}\n"
)

ITEM_APPROVED = "✅ Tasdiqlandi — {scheduled} da chiqadi."
ITEM_REJECTED = "🗑 Bekor qilindi."
ITEM_REGENERATING = "🔄 Qayta yaratilmoqda…"
ITEM_UPDATED = "✏️ Yangilandi. Yangi variant yuqorida 👆"
ITEM_NOT_FOUND = "❌ Post topilmadi (o'chirilgan bo'lishi mumkin)."
ITEM_ALREADY_HANDLED = "ℹ️ Bu post allaqachon ko'rib chiqilgan ({status})."

EDIT_PROMPT = (
    "✏️ <b>Nimani o'zgartiray?</b>\n\n"
    "Yozib yoki ovozli xabar bilan ayting. Masalan:\n"
    "• <i>«Narxni 500 ming qil»</i>\n"
    "• <i>«Birinchi qatorni kuchliroq yoz»</i>\n"
    "• <i>«Emojilarni kamaytir»</i>"
)

RESCHEDULE_PROMPT = (
    "🕐 Yangi vaqtni yuboring.\n\n"
    "Format: <code>KK.OO.YYYY SS:DD</code> (masalan <code>25.08.2026 18:00</code>)\n"
    "yoki shunchaki <code>18:00</code> — bugungi kun uchun."
)

RESCHEDULED = "🕐 Vaqt yangilandi: <b>{scheduled}</b>"

VOICE_PROCESSING = "🎧 Ovozli xabar tinglanmoqda…"
VOICE_HEARD = "🗣 Eshitdim: <i>«{text}»</i>"
VOICE_FAILED = "❌ Ovozni matnga o'girib bo'lmadi. Iltimos, yozib yuboring."

BATCH_APPROVED = "✅ <b>{count} ta post tasdiqlandi.</b> Belgilangan vaqtda avtomatik chiqadi."
BATCH_REJECTED = "🗑 {count} ta post bekor qilindi."

QUICK_PROMPT = "⚡️ Qanday mavzuda post kerak? Qisqacha yozing."
QUICK_GENERATING = "⏳ Post tayyorlanmoqda… Tayyor bo'lgach shu yerga yuboraman."

STATUS_TEXT = (
    "📊 <b>{business}</b>\n\n"
    "├ Ko'rib chiqilmagan: <b>{pending}</b>\n"
    "├ Tasdiqlangan (7 kun): <b>{approved}</b>\n"
    "├ Chop etilgan (jami): <b>{published}</b>\n"
    "├ Xatolik: <b>{failed}</b>\n"
    "└ O'rtacha sifat: <b>{quality}/10</b>\n\n"
    "🧠 Bilim bazasi: {kb_progress}"
)

KB_SUMMARY = (
    "🧠 <b>Bilim bazasi — {business}</b>\n\n"
    "📊 To'ldirilgani: {progress}\n\n"
    "├ Kurslar: <b>{offerings}</b>\n"
    "├ Narxlar: <b>{prices}</b>\n"
    "├ Ustunliklar: <b>{usps}</b>\n"
    "├ O'qituvchilar: <b>{teachers}</b>\n"
    "├ FAQ: <b>{faq}</b>\n"
    "└ Natijalar: <b>{stories}</b>\n\n"
    "{missing}"
)

KB_MISSING = "⚠️ Yetishmayapti: {fields}\n\nTo'ldirish uchun shunchaki yozib yuboring."
KB_COMPLETE = "✅ Hammasi to'ldirilgan."

CANCELLED = "❌ Bekor qilindi."
ERROR_GENERIC = "❌ Xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring."
AI_RATE_LIMITED = (
    "⏳ AI xizmati hozir band (so'rovlar limiti tugadi).\n"
    "Bir necha daqiqadan keyin xabaringizni qayta yuboring — hech narsa yo'qolmaydi."
)
AI_NOT_CONFIGURED = (
    "🔧 AI kaliti sozlanmagan. Administrator `.env` faylida LLM_PROVIDER va mos "
    "API kalitini to'ldirishi kerak."
)
GENERATION_QUEUED = "⏳ Navbatga qo'yildi. Tayyor bo'lgach xabar beraman."

PILLAR_LABELS = {
    ContentPillar.SALES: "💰 Sotuv",
    ContentPillar.EDUCATIONAL: "📚 Ta'limiy",
    ContentPillar.SOCIAL_PROOF: "⭐️ Isbot",
    ContentPillar.INTERACTIVE: "🎯 Interaktiv",
}

TYPE_LABELS = {
    ContentType.FEED_POST: "🖼 Post",
    ContentType.CAROUSEL: "🎠 Karusel",
    ContentType.STORY: "📱 Story",
    ContentType.TELEGRAM_QUIZ: "❓ Quiz",
    ContentType.REELS_SCRIPT: "🎬 Reels",
    ContentType.VIDEO_POST: "🎞 Video",
}

STATUS_LABELS = {
    ContentItemStatus.DRAFT: "qoralama",
    ContentItemStatus.GENERATING: "yaratilmoqda",
    ContentItemStatus.PENDING_REVIEW: "ko'rib chiqilmoqda",
    ContentItemStatus.APPROVED: "tasdiqlangan",
    ContentItemStatus.REJECTED: "bekor qilingan",
    ContentItemStatus.PUBLISHING: "chop etilmoqda",
    ContentItemStatus.PUBLISHED: "chop etilgan",
    ContentItemStatus.FAILED: "xatolik",
}


def quality_bar(score: float) -> str:
    filled = max(0, min(5, round(score / 2)))
    return "🟩" * filled + "⬜️" * (5 - filled)


def pillar_label(pillar: ContentPillar) -> str:
    return PILLAR_LABELS.get(pillar, str(pillar))


def type_label(content_type: ContentType) -> str:
    return TYPE_LABELS.get(content_type, str(content_type))


def status_label(status: ContentItemStatus) -> str:
    return STATUS_LABELS.get(status, str(status))
