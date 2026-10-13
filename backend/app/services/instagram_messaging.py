"""Instagram DMs and comments — reading what arrives, and answering it.

:mod:`app.services.instagram_publisher` pushes content out. This is the other
direction: somebody saw a post and wrote in, and the tier they bought says they
get an answer. Until now `lead_autoreply` was enforced in exactly one place —
the Telegram bot — so an Instagram DM reached nobody at all.

Three things Meta does differently from Telegram, and each one is a way to get
this wrong:

* **Meta pushes, and it does not wait.** A webhook that takes its time gets
  retried and eventually disabled, so the endpoint verifies, hands the payload
  to a worker and returns 200. Nothing that can be slow happens in the request.
* **Anyone can POST to a public webhook.** Every delivery is signed with the
  app secret; an unsigned or mis-signed body is somebody else's traffic, and
  answering it would mean a stranger driving replies from your brand account.
* **A public comment and a DM are different conversations.** A comment gets a
  public reply *and* may get one private message — Meta allows exactly one per
  comment, so it is spent on the answer, never on a greeting.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.core.exceptions import PublishError
from app.core.logging import get_logger
from app.services.http import get_client

log = get_logger(__name__)

#: Instagram's own ceiling on a direct message.
DM_LIMIT = 1000
#: Comment replies are shorter, and a wall of text under a post reads as spam.
COMMENT_LIMIT = 300


@dataclass(slots=True)
class InboundEvent:
    """One thing a stranger did, normalised across the two shapes Meta sends."""

    kind: str                      # "message" | "comment"
    #: The business's own Instagram account id — how the event is routed to a
    #: business, since one webhook serves every client.
    account_id: str = ""
    sender_id: str = ""
    username: str = ""
    text: str = ""
    comment_id: str = ""
    #: Echoes of our own replies come back through the same webhook.
    is_echo: bool = False

    @property
    def answerable(self) -> bool:
        return bool(self.text.strip()) and not self.is_echo and bool(self.sender_id)


def verify_signature(body: bytes, header: str | None, secret: str = "") -> bool:
    """Whether this delivery really came from Meta.

    `hmac.compare_digest` rather than `==`: signature checks that return early
    on the first wrong byte leak the expected value to anyone willing to time
    the endpoint.
    """
    secret = secret or settings.meta_app_secret
    if not secret or not header:
        return False
    prefix, _, sent = header.partition("=")
    if prefix != "sha256" or not sent:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sent)


def parse(payload: dict[str, Any]) -> list[InboundEvent]:
    """Meta's webhook envelope, flattened into events worth answering.

    Unknown shapes are skipped rather than raised on. Meta adds fields and
    event types without warning, and a webhook that 500s on an unfamiliar
    payload gets itself disabled — losing the events it *could* have handled.
    """
    events: list[InboundEvent] = []
    for entry in payload.get("entry") or []:
        account_id = str(entry.get("id") or "")

        for item in entry.get("messaging") or []:
            message = item.get("message") or {}
            events.append(InboundEvent(
                kind="message",
                account_id=account_id,
                sender_id=str((item.get("sender") or {}).get("id") or ""),
                text=str(message.get("text") or ""),
                is_echo=bool(message.get("is_echo")),
            ))

        for change in entry.get("changes") or []:
            if change.get("field") != "comments":
                continue
            value = change.get("value") or {}
            author = value.get("from") or {}
            author_id = str(author.get("id") or "")
            events.append(InboundEvent(
                kind="comment",
                account_id=account_id,
                sender_id=author_id,
                username=str(author.get("username") or ""),
                text=str(value.get("text") or ""),
                comment_id=str(value.get("id") or ""),
                # The account commenting on its own post is us, replying.
                is_echo=bool(author_id and author_id == account_id),
            ))
    return events


@dataclass(slots=True)
class InstagramMessenger:
    """Outbound half: replies, sent as the business's own account."""

    token: str
    account_id: str
    sent: list[str] = field(default_factory=list)

    async def _post(self, path: str, **payload: Any) -> dict[str, Any]:
        client = await get_client("instagram", timeout=60)
        url = f"{settings.graph_api_url}/{path.lstrip('/')}"
        data = {k: v for k, v in payload.items() if v is not None}
        data["access_token"] = self.token
        try:
            response = await client.post(url, data=data)
            body = response.json()
        except Exception as exc:
            raise PublishError("instagram", f"network error: {exc}", retryable=True) from exc
        if "error" in body:
            error = body["error"]
            raise PublishError(
                "instagram",
                f"{error.get('message', 'unknown')} (code {error.get('code')})",
                retryable=bool(error.get("is_transient")),
                details=error,
            )
        return body

    async def send_dm(self, recipient_id: str, text: str) -> dict[str, Any]:
        return await self._post(
            f"{self.account_id}/messages",
            recipient=f'{{"id":"{recipient_id}"}}',
            message=f'{{"text":{_json_string(text[:DM_LIMIT])}}}',
        )

    async def reply_to_comment(self, comment_id: str, text: str) -> dict[str, Any]:
        """A public reply, threaded under the comment."""
        return await self._post(f"{comment_id}/replies", message=text[:COMMENT_LIMIT])

    async def private_reply(self, comment_id: str, text: str) -> dict[str, Any]:
        """The one DM a comment earns.

        Meta allows exactly one private reply per comment and only within seven
        days, so it carries the answer — never a greeting that spends the
        allowance on nothing.
        """
        return await self._post(
            f"{self.account_id}/messages",
            recipient=f'{{"comment_id":"{comment_id}"}}',
            message=f'{{"text":{_json_string(text[:DM_LIMIT])}}}',
        )


def _json_string(value: str) -> str:
    """Quote a string for the JSON-in-a-form-field Meta expects here."""
    import json

    return json.dumps(value, ensure_ascii=False)
