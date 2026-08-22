"""Telegram approval bot (aiogram 3).

Kept intentionally free of imports: handler modules do ``from app.bot import
texts`` while the package itself is still initialising, so re-exporting the
dispatcher here would create an import cycle. Import ``app.bot.main`` directly.
"""
