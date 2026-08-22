"""Concrete facts the copy must actually contain.

The knowledge base reaches the model as one JSON blob, and small models
reliably ignore the numbers inside it — the editor then scores the post low
for being fact-free. So the facts relevant to the topic are pulled out, put
in front of the model as an explicit requirement, and checked afterwards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.knowledge_base import KnowledgeBase

#: More than this and the model starts cramming every number into one post.
MAX_FACTS = 5
#: Words too common to say anything about which offering a topic is about.
STOPWORDS = frozenset(
    {
        "kurs", "kurslar", "kursi", "uchun", "bilan", "haqida", "yangi", "bizning",
        "markaz", "markazi", "maktab", "dars", "darslar", "tili", "til", "va",
    }
)


@dataclass(frozen=True, slots=True)
class Fact:
    """One thing the copy can state, plus how to tell whether it did."""

    label: str                   # what it is, e.g. "Backend dasturlash"
    value: str                   # the concrete part, e.g. "800 000 so'm (oyiga)"
    tokens: tuple[str, ...]      # normalised forms that count as "mentioned"

    @property
    def text(self) -> str:
        return f"{self.label} — {self.value}" if self.value else self.label

    @property
    def is_priced(self) -> bool:
        return any(char.isdigit() for char in self.value)


def _normalise(value: str) -> str:
    """Lowercase, strip punctuation and spaces — so `800 000` == `800000`."""
    return re.sub(r"[^0-9a-zЀ-ӿ']+", "", value.lower().replace("'", "'"))


def _price_tokens(amount: int) -> tuple[str, ...]:
    """Every way a price is normally written in Uzbek copy."""
    tokens = {str(amount)}
    if amount >= 1000 and amount % 1000 == 0:
        thousands = amount // 1000
        tokens.add(f"{thousands}ming")
    return tuple(tokens)


def _keywords(value: str) -> set[str]:
    words = re.findall(r"[\w']+", value.lower())
    return {w for w in words if len(w) > 3 and w not in STOPWORDS}


def _relevance(candidate: str, topic: str) -> int:
    return len(_keywords(candidate) & _keywords(topic))


def collect_facts(kb: KnowledgeBase | None, topic: str = "", limit: int = MAX_FACTS) -> list[Fact]:
    """Pick the facts worth demanding for this topic, most relevant first."""
    if kb is None:
        return []

    scored: list[tuple[int, Fact]] = []

    for entry in kb.prices or []:
        item = str(entry.get("item", "")).strip()
        amount = entry.get("price")
        if not item or not isinstance(amount, (int, float)):
            continue
        amount = int(amount)
        note = str(entry.get("note", "")).strip()
        currency = str(entry.get("currency", "UZS")).strip()
        unit = "so'm" if currency.upper() == "UZS" else currency
        value = f"{amount:,}".replace(",", " ") + f" {unit}"
        if note:
            value += f" ({note})"
        scored.append((_relevance(item, topic) + 2, Fact(item, value, _price_tokens(amount))))

    for entry in kb.key_offerings or []:
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        description = str(entry.get("description", "")).strip()
        token = _normalise(sorted(_keywords(name), key=len, reverse=True)[0]) if _keywords(name) else ""
        if token:
            scored.append((_relevance(name, topic), Fact(name, description, (token,))))

    scored.sort(key=lambda pair: pair[0], reverse=True)

    facts: list[Fact] = []
    seen: set[str] = set()
    for _, fact in scored:
        if fact.text in seen:
            continue
        seen.add(fact.text)
        facts.append(fact)
        if len(facts) >= limit:
            break
    return facts


def render_block(facts: list[Fact]) -> str:
    """The requirement as the model sees it — last block wins attention."""
    if not facts:
        return ""
    lines = "\n".join(f"- {fact.text}" for fact in facts)
    return (
        "MAJBURIY FAKTLAR — matnda KAMIDA BITTASI aynan shu raqam/nom bilan "
        "yozilishi SHART (faktsiz post qabul qilinmaydi):\n"
        f"{lines}\n"
        "Raqamni o'zgartirma, taxminiy yozma, «arzon narxlarda» kabi umumiy "
        "iboralar bilan almashtirma."
    )


def mentions_a_fact(text: str, facts: list[Fact]) -> bool:
    """Did the copy actually state one of them?"""
    if not facts:
        return True                      # nothing was required
    haystack = _normalise(text or "")
    return any(token and token in haystack for fact in facts for token in fact.tokens)


def render_inline_block(facts: list[Fact], limit: int = 3) -> str:
    """The facts as copy, for when the model refuses to write them itself.

    Small models ignore the requirement even when told twice, so the last
    resort is to state the facts in code rather than ship a fact-free post.
    Only priced items are used — a bare course name adds nothing here.
    """
    chosen = [fact for fact in facts if fact.is_priced][:limit]
    if not chosen:
        return ""
    lines = "\n".join(f"— {fact.label}: {fact.value}" for fact in chosen)
    return f"📌 Narxlar:\n{lines}"


def retry_instruction(facts: list[Fact]) -> str:
    lines = "\n".join(f"- {fact.text}" for fact in facts[:3])
    return (
        "AVVALGI URINISHDA BIRORTA HAM ANIQ FAKT YO'Q EDI. "
        "Bu safar quyidagilardan kamida bittasini matn ichida aynan yoz:\n"
        f"{lines}"
    )
