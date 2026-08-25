"""The line under the business name on the closing card.

It used to be `"Bilim Shahri sizni kutmoqda"` — one client's corporate
positioning, hardcoded into the shared outro. Every other business signed its
video off with a language centre's slogan: a bakery, a clinic, a barbershop.

The card is still deterministic — that part was right, and a model inventing a
slogan per clip would be worse. What changed is where the words come from.
"""

from __future__ import annotations

from app.agents.kinetic import TAGLINE_MAX, outro_tagline
from app.services.brand_kit import BrandKit, kit_for
from tests.test_agents import make_business, make_knowledge


def knowledge_with(*, tagline: str = "", usps: list[str] | None = None):
    knowledge = make_knowledge()
    knowledge.brand_kit = {"tagline": tagline} if tagline else {}
    knowledge.usps = usps if usps is not None else []
    return knowledge


class TestTaglineSource:
    def test_the_brand_kit_wins(self):
        assert outro_tagline(knowledge_with(tagline="Non issiq chiqadi")) == "Non issiq chiqadi"

    def test_a_usp_stands_in_when_no_tagline_is_set(self):
        """The closest thing to a slogan the knowledge base already holds."""
        assert outro_tagline(knowledge_with(usps=["8.0 ballik o'qituvchi"])) == "8.0 ballik o'qituvchi"

    def test_the_tagline_beats_a_usp(self):
        knowledge = knowledge_with(tagline="Non issiq chiqadi", usps=["24 soat ochiq"])
        assert outro_tagline(knowledge) == "Non issiq chiqadi"

    def test_nothing_set_means_nothing_shown(self):
        """A borrowed slogan is worse than none; the name and logo suffice."""
        assert outro_tagline(knowledge_with()) == ""

    def test_no_knowledge_base_at_all(self):
        assert outro_tagline(None) == ""

    def test_no_client_slogan_survives_in_the_code(self):
        """The regression this file exists for."""
        import inspect

        from app.agents import kinetic

        assert "Bilim Shahri" not in inspect.getsource(kinetic)


class TestItFitsTheCard:
    """Drawn centred at font 32 on a fixed-width card — it cannot reflow."""

    def test_a_usp_too_long_for_the_card_is_skipped_not_truncated(self):
        long_usp = "Bizda " + "juda " * 30 + "yaxshi"
        knowledge = knowledge_with(usps=[long_usp, "10 yil tajriba"])

        assert outro_tagline(knowledge) == "10 yil tajriba"

    def test_a_long_tagline_is_dropped_rather_than_cut_mid_word(self):
        """A slogan sliced in half reads as a bug, not as brevity."""
        assert outro_tagline(knowledge_with(tagline="x" * (TAGLINE_MAX + 1))) == ""

    def test_a_tagline_exactly_at_the_limit_is_kept(self):
        text = "x" * TAGLINE_MAX
        assert outro_tagline(knowledge_with(tagline=text)) == text

    def test_whitespace_is_not_a_tagline(self):
        assert outro_tagline(knowledge_with(tagline="   ", usps=["   ", "10 yil"])) == "10 yil"


class TestBrandKitCarriesIt:
    def test_the_field_exists_and_defaults_empty(self):
        assert BrandKit().tagline == ""

    def test_it_is_read_back_out_of_storage(self):
        assert kit_for({"tagline": "Non issiq chiqadi"}).tagline == "Non issiq chiqadi"

    def test_a_stored_non_string_does_not_crash_the_kit(self):
        assert kit_for({"tagline": 42}).tagline == "42"
        assert kit_for({"tagline": None}).tagline == ""

    def test_an_empty_kit_still_loads(self):
        assert kit_for(None).tagline == ""
        assert kit_for({}).tagline == ""


class TestTheOutroScene:
    """The scene the agent appends, built from the same source."""

    def test_the_card_carries_the_name_and_the_brand_line(self):
        from app.agents.kinetic import build_outro

        scene = build_outro(make_business(), knowledge_with(tagline="Non issiq chiqadi"))

        assert scene.kind == "outro"
        assert scene.text == make_business().name
        assert scene.sub == "Non issiq chiqadi"

    def test_without_a_brand_line_the_card_shows_only_the_name(self):
        from app.agents.kinetic import build_outro

        scene = build_outro(make_business(), knowledge_with())

        assert scene.text == make_business().name
        assert scene.sub == ""
