"""Bitta biznesning o'z Telegram botini chatbot sifatida ulash.

Ishlatish (api konteyneri ichida):

    docker compose exec api python scripts/connect_chatbot.py "Shanghai School" \\
        --token 123:ABC --channel @kanal_nomi [--discussion -100123]

Tokenni (shifrlangan holda) saqlaydi, kanalni yozadi va botning webhook'ini
`<PUBLIC_BASE_URL>/telegram/chat/<business_id>/webhook` ga yo'naltiradi.
Platformaning admin boti tokeni rad etiladi — u polling bilan ishlaydi.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select


async def main(args: argparse.Namespace) -> int:
    from app.core.exceptions import ConfigurationError
    from app.db.session import session_scope
    from app.models.business import Business, BusinessCredentials
    from app.services.telegram_chat import connect

    async with session_scope() as session:
        business = (await session.execute(
            select(Business).where(func.lower(Business.name) == args.business.lower())
        )).scalars().one_or_none()
        if business is None:
            print(f"Biznes topilmadi: {args.business}", file=sys.stderr)
            return 1
        if not business.capabilities.lead_autoreply:
            print(f"{business.name} tarifi ({business.plan}) avto-javobni o'z ichiga olmaydi",
                  file=sys.stderr)
            return 1
        credentials = (await session.execute(
            select(BusinessCredentials).where(BusinessCredentials.business_id == business.id)
        )).scalars().one_or_none()
        if credentials is None:
            credentials = BusinessCredentials(business_id=business.id)
            session.add(credentials)

        token = args.token or credentials.tg_bot_token or ""
        try:
            result = await connect(business.id, token)
        except ConfigurationError as exc:
            print(f"Ulanmadi: {exc}", file=sys.stderr)
            return 1

        credentials.tg_bot_token = token
        credentials.telegram_enabled = True
        if args.channel:
            credentials.tg_channel_id = args.channel
        if args.discussion:
            credentials.tg_discussion_chat_id = args.discussion
        business_name, channel = business.name, credentials.tg_channel_id

    print(f"✅ {business_name} → @{result['bot']}")
    print(f"   webhook: {result['url']}")
    print(f"   kanal:   {channel or '— (kommentlarga javob berilmaydi)'}")
    if not result["can_read_groups"]:
        print("   ⚠️  Bot guruhdagi hamma xabarni ko'rmaydi. Kommentlar uchun botni "
              "muhokama guruhiga ADMIN qiling yoki BotFather → /setprivacy → Disable.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("business", help="Biznes nomi, masalan \"Shanghai School\"")
    parser.add_argument("--token", help="BotFather bergan token (biznesning O'Z boti)")
    parser.add_argument("--channel", help="@kanal yoki -100… id")
    parser.add_argument("--discussion", help="Kanalga bog'langan muhokama guruhi id'si")
    sys.exit(asyncio.run(main(parser.parse_args())))
