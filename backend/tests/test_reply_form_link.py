"""A public comment ends with the enrolment form, not a request for a number.

Under a channel post everyone reads the thread, so asking for a phone there is
asking someone to publish it. The site's own form writes to the CRM, so the
link is the safer funnel — and it is appended in code, because a model asked to
copy a URL will one day shorten, translate or "fix" it.
"""

from __future__ import annotations

from app.agents.reply import MAX_CHARS, with_form_link

FORM = "https://shanghai-edu.uz/website/#enroll"


class TestWithFormLink:
    def test_the_link_is_appended_verbatim(self):
        text = with_form_link("Ingliz tili oyiga 350 000 so'm.", FORM)
        assert text.startswith("Ingliz tili oyiga 350 000 so'm.")
        assert text.rstrip().endswith(FORM)

    def test_no_link_configured_leaves_the_answer_alone(self):
        assert with_form_link("Javob.", "") == "Javob."

    def test_an_empty_answer_stays_empty_for_a_human_to_take(self):
        assert with_form_link("", FORM) == ""

    def test_a_long_answer_is_cut_so_the_link_survives(self):
        text = with_form_link("a" * 1000, FORM)
        assert len(text) <= MAX_CHARS
        assert text.endswith(FORM)

    def test_a_link_the_model_already_wrote_is_not_repeated(self):
        text = with_form_link(f"Bu yerda yoziling: {FORM}", FORM)
        assert text.count(FORM) == 1
