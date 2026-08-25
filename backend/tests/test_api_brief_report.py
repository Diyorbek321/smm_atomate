"""Serialisation of the brief and report endpoints.

Both services return frozen slots dataclasses, which have no `__dict__` — the
first version of these endpoints called `vars()` on them and returned a 500 in
production while every service-level test stayed green. The layer that
converts one to the other is worth its own test.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from app.models.business import Business
from app.models.enums import BusinessCategory, Language, Plan, ToneOfVoice
from app.schemas.report import TopPostRead
from app.schemas.shooting import ShotRead
from app.services.client_report import TopPost
from app.services.shooting_brief import build_brief


def make_business() -> Business:
    return Business(
        name="Postchi",
        plan=Plan.PRO,
        category=BusinessCategory.TECH,
        tone_of_voice=ToneOfVoice.EXPERT,
        target_audience="mahalliy biznes",
        language=Language.UZ,
        timezone="Asia/Tashkent",
        settings={},
    )


class TestShotSerialisation:
    def test_every_shot_converts_to_its_wire_model(self):
        brief = build_brief(make_business(), None, date(2026, 9, 1))
        assert brief.shots
        for shot in brief.shots:
            wire = ShotRead(**asdict(shot))
            assert wire.title == shot.title
            assert wire.kind in ("video", "photo")

    def test_vars_would_not_work_on_a_shot(self):
        """Pin the reason `asdict` is used, so nobody 'simplifies' it back."""
        shot = build_brief(make_business(), None, date(2026, 9, 1)).shots[0]
        try:
            vars(shot)
        except TypeError:
            return
        raise AssertionError("Shot endi __dict__ ga ega — asdict() shart emas bo'lishi mumkin")


class TestTopPostSerialisation:
    def test_a_top_post_converts_to_its_wire_model(self):
        post = TopPost(headline="Sentabr qabuli", content_type="post",
                       reactions=12, published_on=date(2026, 7, 5))
        wire = TopPostRead(**asdict(post))
        assert wire.headline == "Sentabr qabuli"
        assert wire.reactions == 12

    def test_an_unmeasured_post_keeps_a_null_reaction_count(self):
        post = TopPost(headline="O'lchanmagan", content_type="post",
                       reactions=None, published_on=date(2026, 7, 5))
        assert TopPostRead(**asdict(post)).reactions is None
