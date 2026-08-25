"""Facts the copy is required to state, and the check that it did."""

from __future__ import annotations

from app.agents.facts import (
    collect_facts,
    mentions_a_fact,
    render_block,
    retry_instruction,
)
from app.models.knowledge_base import KnowledgeBase

KB = KnowledgeBase(
    prices=[
        {"item": "Til kurslari", "price": 350000, "currency": "UZS", "note": "oyiga"},
        {"item": "Backend dasturlash", "price": 800000, "currency": "UZS", "note": "oyiga"},
        {"item": "Kompyuter savodxonligi", "price": 500000, "currency": "UZS"},
    ],
    key_offerings=[
        {"name": "Ingliz tili kursi", "description": "Barcha darajalar"},
        {"name": "Mental arifmetika", "description": ""},
    ],
    # Column defaults only apply on insert; this KB is never saved.
    preferred_hashtags=[],
    banned_topics=[],
    usps=[],
    faq=[],
    teacher_profiles=[],
    success_stories=[],
)


class TestCollecting:
    def test_prices_come_first(self):
        """A number is the most convincing fact a post can carry."""
        facts = collect_facts(KB, "yangi qabul")
        assert "so'm" in facts[0].text

    def test_the_topic_pulls_its_own_price_to_the_top(self):
        facts = collect_facts(KB, "Backend dasturlash kursiga qabul")
        assert facts[0].text.startswith("Backend dasturlash")

    def test_a_different_topic_reorders(self):
        facts = collect_facts(KB, "Kompyuter savodxonligi darslari")
        assert facts[0].text.startswith("Kompyuter savodxonligi")

    def test_prices_are_formatted_for_humans(self):
        [fact] = [f for f in collect_facts(KB, "backend") if f.text.startswith("Backend")]
        assert "800 000 so'm" in fact.text and "(oyiga)" in fact.text

    def test_a_missing_note_is_not_rendered_as_empty_brackets(self):
        [fact] = [f for f in collect_facts(KB, "kompyuter") if f.text.startswith("Kompyuter")]
        assert "()" not in fact.text

    def test_the_list_is_capped(self):
        assert len(collect_facts(KB, "", limit=2)) == 2

    def test_no_knowledge_base_means_no_demands(self):
        assert collect_facts(None, "mavzu") == []

    def test_malformed_entries_are_skipped(self):
        kb = KnowledgeBase(prices=[{"item": "", "price": 1}, {"item": "X"}, {"item": "Y", "price": "arzon"}])
        assert collect_facts(kb, "") == []


class TestDetection:
    FACTS = collect_facts(KB, "Backend dasturlash")

    def test_a_spaced_price_counts(self):
        assert mentions_a_fact("Backend kursi oyiga 800 000 so'm", self.FACTS) is True

    def test_the_ming_spelling_counts(self):
        """Copy usually writes 800 ming, not 800000."""
        assert mentions_a_fact("Narxi — 800 ming so'm", self.FACTS) is True

    def test_a_bare_number_counts(self):
        assert mentions_a_fact("800000 so'm", self.FACTS) is True

    def test_vague_copy_does_not_count(self):
        assert mentions_a_fact("Arzon narxlarda sifatli ta'lim", self.FACTS) is False

    def test_an_offering_name_counts(self):
        assert mentions_a_fact("Ingliz tili kursi ochildi", self.FACTS) is True

    def test_a_wrong_number_does_not_count(self):
        assert mentions_a_fact("Narxi 999 000 so'm", self.FACTS) is False

    def test_nothing_required_means_nothing_to_fail(self):
        assert mentions_a_fact("umumiy matn", []) is True

    def test_empty_copy_fails(self):
        assert mentions_a_fact("", self.FACTS) is False


class TestPromptBlocks:
    def test_the_block_names_every_fact(self):
        block = render_block(collect_facts(KB, "backend"))
        assert "MAJBURIY FAKTLAR" in block
        assert "800 000 so'm" in block

    def test_the_block_forbids_vague_substitutes(self):
        assert "arzon narxlarda" in render_block(collect_facts(KB, "")).lower()

    def test_no_facts_means_no_block(self):
        assert render_block([]) == ""

    def test_the_retry_names_a_few_concretely(self):
        instruction = retry_instruction(collect_facts(KB, "backend"))
        assert "800 000 so'm" in instruction
        assert instruction.count("- ") <= 3


class TestCopywriterRetries:
    """The agent gets one sharper attempt before giving up on facts."""

    def _agent_and_request(self, monkeypatch, replies):
        from app.agents.copywriter import CopyRequest, CopywriterAgent
        from app.models.business import Business
        from app.models.enums import BusinessCategory, ContentPillar, ContentType, Plan
        from app.schemas.content import CopyOutputStrict

        agent = CopywriterAgent()
        prompts: list[str] = []

        async def fake_ask_json(prompt, schema, **kwargs):
            prompts.append(prompt)
            return CopyOutputStrict(**replies[min(len(prompts) - 1, len(replies) - 1)])

        async def fake_system_prompt(*args, **kwargs):
            return "system"

        monkeypatch.setattr(agent, "ask_json", fake_ask_json)
        monkeypatch.setattr(agent, "system_prompt", fake_system_prompt)

        request = CopyRequest(
            business=Business(name="Shanghai School", plan=Plan.PRO,
                              category=BusinessCategory.EDUCATION, settings={}),
            knowledge=KB,
            content_type=ContentType.FEED_POST,
            pillar=ContentPillar.SALES,
            topic="Backend dasturlash kursiga qabul",
        )
        return agent, request, prompts

    def _reply(self, caption: str) -> dict:
        return {
            "headline": "Sarlavha", "hook": "Hook", "cta": "Yozilish",
            "caption_tg": caption, "caption_ig": caption, "hashtags": [],
        }

    async def test_the_prompt_carries_the_requirement(self, monkeypatch):
        agent, request, prompts = self._agent_and_request(
            monkeypatch, [self._reply("Backend kursi — 800 000 so'm")]
        )
        await agent.run(request)
        assert len(prompts) == 1                       # no retry needed
        assert "MAJBURIY FAKTLAR" in prompts[0]

    async def test_fact_free_copy_is_retried_once(self, monkeypatch):
        agent, request, prompts = self._agent_and_request(
            monkeypatch,
            [self._reply("Arzon narxlarda sifatli ta'lim"),
             self._reply("Backend kursi — 800 000 so'm")],
        )
        copy = await agent.run(request)
        assert len(prompts) == 2
        assert "AVVALGI URINISHDA BIRORTA HAM ANIQ FAKT YO'Q" in prompts[1]
        assert "800 000" in copy.caption_tg

    async def test_it_gives_up_after_one_retry(self, monkeypatch):
        """Two bad attempts return the copy anyway — an empty post is worse."""
        agent, request, prompts = self._agent_and_request(
            monkeypatch, [self._reply("Arzon narxlarda sifatli ta'lim")]
        )
        copy = await agent.run(request)
        assert len(prompts) == 2
        assert copy.caption_tg


class TestInjection:
    """When the model will not state a fact, the code states it instead."""

    FACTS = collect_facts(KB, "yangi qabul")

    def test_the_block_lists_prices_readably(self):
        from app.agents.facts import render_inline_block

        block = render_inline_block(self.FACTS)
        assert block.startswith("📌 Narxlar:")
        assert "— Til kurslari: 350 000 so'm (oyiga)" in block
        assert " — — " not in block

    def test_it_is_capped(self):
        from app.agents.facts import render_inline_block

        assert render_inline_block(self.FACTS, limit=2).count("—") == 2

    def test_unpriced_offerings_are_left_out(self):
        """A bare course name adds nothing to a price list."""
        from app.agents.facts import render_inline_block

        assert "Mental arifmetika" not in render_inline_block(self.FACTS)

    def test_nothing_priced_falls_back_to_named_offerings(self):
        """No price in the base is not a reason to ship a post about nothing."""
        from app.agents.facts import collect_facts as collect
        from app.agents.facts import render_inline_block

        kb = KnowledgeBase(
            prices=[], key_offerings=[{"name": "Ingliz tili", "description": "hammasi"}],
            preferred_hashtags=[], banned_topics=[], usps=[], faq=[],
            teacher_profiles=[], success_stories=[],
        )
        block = render_inline_block(collect(kb, ""))
        assert "Ingliz tili" in block

    def test_no_facts_at_all_means_no_block(self):
        from app.agents.facts import render_inline_block

        assert render_inline_block([]) == ""

    def test_the_injected_block_satisfies_the_check(self):
        """Whatever we append must pass the same test the model had to pass."""
        from app.agents.facts import mentions_a_fact, render_inline_block

        assert mentions_a_fact(render_inline_block(self.FACTS), self.FACTS) is True

    async def test_the_agent_falls_back_to_injection(self, monkeypatch):
        agent, request, prompts = TestCopywriterRetries()._agent_and_request(
            monkeypatch, [TestCopywriterRetries()._reply("Arzon narxlarda sifatli ta'lim")]
        )
        copy = await agent.run(request)

        assert len(prompts) == 2                       # asked twice, then gave up asking
        assert "📌 Narxlar:" in copy.caption_tg
        assert "800 000 so'm" in copy.caption_tg
        assert "📌 Narxlar:" in copy.caption_ig


class TestContactDeduplication:
    """The same phone number twice in one caption reads as careless."""

    def test_a_written_number_is_recognised(self):
        from app.agents.copywriter import _states_the_phone

        assert _states_the_phone("Qo'ng'iroq qiling: +998931913308", "+998931913308") is True

    def test_spacing_and_punctuation_do_not_matter(self):
        from app.agents.copywriter import _states_the_phone

        assert _states_the_phone("Telefon 93 191 33 08 ga yozing", "+998931913308") is True

    def test_a_different_number_does_not_count(self):
        from app.agents.copywriter import _states_the_phone

        assert _states_the_phone("Boshqa raqam +998901234567", "+998931913308") is False

    def test_no_number_at_all(self):
        from app.agents.copywriter import _states_the_phone

        assert _states_the_phone("Bizga yozing", "+998931913308") is False

    def test_a_nonsense_phone_is_never_matched(self):
        from app.agents.copywriter import _states_the_phone

        assert _states_the_phone("12345", "123") is False

    async def test_the_contact_block_is_skipped_when_already_present(self, monkeypatch):
        kb = KnowledgeBase(
            prices=[{"item": "Backend", "price": 800000, "currency": "UZS"}],
            key_offerings=[], phone="+998931913308", address="Angren shahri",
            preferred_hashtags=[], banned_topics=[], usps=[], faq=[],
            teacher_profiles=[], success_stories=[],
        )
        helper = TestCopywriterRetries()
        agent, request, _ = helper._agent_and_request(
            monkeypatch,
            [{**helper._reply("Backend — 800 000 so'm. Qo'ng'iroq: +998931913308"),
              "cta": "Qo'ng'iroq qiling: +998931913308"}],
        )
        request.knowledge = kb
        copy = await agent.run(request)

        assert copy.caption_tg.count("998931913308") == 1

    async def test_the_contact_block_is_added_when_missing(self, monkeypatch):
        kb = KnowledgeBase(
            prices=[{"item": "Backend", "price": 800000, "currency": "UZS"}],
            key_offerings=[], phone="+998931913308", address="Angren shahri",
            preferred_hashtags=[], banned_topics=[], usps=[], faq=[],
            teacher_profiles=[], success_stories=[],
        )
        helper = TestCopywriterRetries()
        agent, request, _ = helper._agent_and_request(
            monkeypatch,
            [{**helper._reply("Backend kursi — 800 000 so'm"), "cta": "Bizga yozing"}],
        )
        request.knowledge = kb
        copy = await agent.run(request)

        assert "998931913308" in copy.caption_tg
        assert "Angren shahri" in copy.caption_tg
