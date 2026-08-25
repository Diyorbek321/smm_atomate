"""Reading a public Telegram channel, without touching the network.

The page is Telegram's, so the parser is written against a captured sample of
their markup rather than a mock: when they change the class names this file is
what notices. Every test here is pure — `fetch_channel` and `scout` are the
only things that reach out, and they are covered through a stubbed transport.
"""

from __future__ import annotations

import pytest

from app.services.telegram_scout import (
    ChannelSnapshot,
    ScoutPost,
    extract_handle,
    own_channel_handle,
    parse_channel,
    parse_count,
    unresolved,
)


def post_block(*, text: str = "Salom", views: str = "1.2K", when: str = "2026-08-01T10:00:00+00:00",
               media: str = "", post_id: str = "kanal/1") -> str:
    """One message as t.me/s/ serves it, trimmed to the parts we read."""
    media_html = ""
    if media == "video":
        media_html = '<a class="tgme_widget_message_video_player"><i class="tgme_widget_message_video_thumb"></i></a>'
    elif media == "photo":
        media_html = '<a class="tgme_widget_message_photo_wrap" style="background-image:url(x)"></a>'
    return (
        f'<div class="tgme_widget_message_wrap js-widget_message_wrap">'
        f'<div class="tgme_widget_message" data-post="{post_id}">'
        f"{media_html}"
        f'<div class="tgme_widget_message_text js-message_text" dir="auto">{text}</div>'
        f'<div class="tgme_widget_message_info">'
        f'<span class="tgme_widget_message_views">{views}</span>'
        f'<a class="tgme_widget_message_date"><time datetime="{when}" class="time">10:00</time></a>'
        f"</div></div></div>"
    )


def page(*blocks: str, subscribers: str = "3.4K") -> str:
    header = (
        '<div class="tgme_channel_info_counters"><div class="tgme_channel_info_counter">'
        f'<span class="counter_value">{subscribers}</span> '
        '<span class="counter_type">subscribers</span></div></div>'
    )
    return f"<html><body>{header}{''.join(blocks)}</body></html>"


# --------------------------------------------------------------------------- #
# Handles
# --------------------------------------------------------------------------- #
class TestExtractHandle:
    @pytest.mark.parametrize(
        "value",
        ["@najottalim", "najottalim", "t.me/najottalim", "https://t.me/najottalim",
         "https://t.me/s/najottalim", "t.me/najottalim/"],
    )
    def test_every_shape_an_owner_types(self, value):
        assert extract_handle(value) == "najottalim"

    def test_a_plain_name_is_not_a_channel(self):
        """No search API here, so a name cannot become a handle by guessing."""
        assert extract_handle("Najot Ta'lim") is None

    def test_an_invite_link_is_not_a_public_channel(self):
        assert extract_handle("https://t.me/joinchat/AAAAAE") is None

    def test_too_short_is_rejected(self):
        assert extract_handle("@abc") is None

    def test_empty(self):
        assert extract_handle("") is None
        assert extract_handle("   ") is None

    def test_names_are_reported_rather_than_dropped(self):
        assert unresolved(["@birkanal", "Najot Ta'lim", "  ", "ikki markaz"]) == [
            "Najot Ta'lim",
            "ikki markaz",
        ]


class TestOwnChannel:
    def test_a_numeric_id_has_no_preview_page(self):
        assert own_channel_handle(type("C", (), {"tg_channel_id": "-1001234567890"})) is None

    def test_a_public_username_does(self):
        assert own_channel_handle(type("C", (), {"tg_channel_id": "@shanghai"})) == "shanghai"

    def test_missing_credentials(self):
        assert own_channel_handle(None) is None
        assert own_channel_handle(type("C", (), {"tg_channel_id": None})) is None


# --------------------------------------------------------------------------- #
# Counts
# --------------------------------------------------------------------------- #
class TestParseCount:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("482", 482), ("1.2K", 1200), ("14.7M", 14_700_000), ("23M", 23_000_000),
         ("1,024", 1024), ("", 0), ("—", 0), ("nonsense", 0)],
    )
    def test_telegram_abbreviations_become_integers(self, value, expected):
        assert parse_count(value) == expected


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
class TestParseChannel:
    def test_reads_text_views_date_and_subscribers(self):
        snapshot = parse_channel(page(post_block(text="IELTS 7.0 natija", views="900")), "kanal")

        assert snapshot.subscribers == 3400
        assert len(snapshot.posts) == 1
        post = snapshot.posts[0]
        assert post.text == "IELTS 7.0 natija"
        assert post.views == 900
        assert post.posted_at is not None and post.posted_at.year == 2026
        assert post.post_id == "kanal/1"

    def test_markup_and_entities_are_stripped_from_the_words(self):
        snapshot = parse_channel(
            page(post_block(text="<b>Narx</b>&nbsp;600&nbsp;000<br/>so&#39;m")), "kanal"
        )
        assert snapshot.posts[0].text == "Narx 600 000\nso'm"

    def test_media_type_is_the_format_signal(self):
        snapshot = parse_channel(
            page(
                post_block(media="video", post_id="k/1"),
                post_block(media="photo", post_id="k/2"),
                post_block(post_id="k/3"),
            ),
            "kanal",
        )
        assert [p.media for p in snapshot.posts] == ["video", "rasm", "matn"]

    def test_service_messages_are_skipped(self):
        """A block with no words and no views is not a post."""
        noise = '<div class="tgme_widget_message_wrap"><div class="tgme_widget_message_service">joined</div></div>'
        snapshot = parse_channel(page(noise, post_block()), "kanal")
        assert len(snapshot.posts) == 1

    def test_an_empty_preview_yields_nothing(self):
        assert parse_channel("<html><body>preview unavailable</body></html>", "kanal").posts == []

    def test_a_broken_timestamp_does_not_lose_the_post(self):
        block = post_block(when="not-a-date")
        snapshot = parse_channel(page(block), "kanal")
        assert len(snapshot.posts) == 1
        assert snapshot.posts[0].posted_at is None


# --------------------------------------------------------------------------- #
# Ranking — the part that makes channels comparable
# --------------------------------------------------------------------------- #
class TestRanking:
    @staticmethod
    def _snapshot(*views: int) -> ChannelSnapshot:
        snapshot = ChannelSnapshot(
            handle="kanal",
            posts=[ScoutPost(handle="kanal", text=f"post {i}", views=v) for i, v in enumerate(views)],
        )
        snapshot.rank()
        return snapshot

    def test_lift_is_measured_against_the_channels_own_median(self):
        snapshot = self._snapshot(100, 100, 100, 400)
        assert snapshot.median_views == 100
        assert snapshot.posts[-1].lift == 4.0

    def test_a_small_channel_can_outrank_a_large_one(self):
        """The reason ranking is per channel and never on raw views."""
        small = self._snapshot(100, 100, 100, 400)
        large = self._snapshot(1_000_000, 1_000_000, 1_000_000, 1_100_000)

        assert small.posts[-1].lift > large.posts[-1].lift
        assert small.posts[-1].views < large.posts[-1].views

    def test_ordinary_posts_are_not_outperformers(self):
        snapshot = self._snapshot(100, 100, 100, 110)
        assert snapshot.outperformers() == []

    def test_outperformers_come_back_strongest_first(self):
        snapshot = self._snapshot(100, 100, 100, 400, 250)
        lifts = [p.lift for p in snapshot.outperformers()]
        assert lifts == sorted(lifts, reverse=True)

    def test_a_post_without_words_is_not_a_lesson(self):
        snapshot = ChannelSnapshot(
            handle="k",
            posts=[
                ScoutPost(handle="k", text="", views=400),
                ScoutPost(handle="k", text="bor", views=100),
                ScoutPost(handle="k", text="bor", views=100),
                ScoutPost(handle="k", text="bor", views=100),
            ],
        )
        snapshot.rank()
        assert snapshot.outperformers() == []

    def test_too_few_measured_posts_is_not_a_baseline(self):
        assert self._snapshot(100, 200).is_usable is False
        assert self._snapshot(100, 200, 300).is_usable is True

    def test_a_channel_with_no_view_counts_survives_without_dividing_by_zero(self):
        snapshot = self._snapshot(0, 0, 0)
        assert snapshot.median_views == 0
        assert all(p.lift == 0.0 for p in snapshot.posts)


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
class TestFetching:
    @staticmethod
    def _stub(monkeypatch, pages: dict[str, str], *, fail: set[str] | None = None):
        from app.services import telegram_scout as module

        asked: list[str] = []

        async def fake_request(provider, method, url, **kwargs):
            handle = url.rstrip("/").rsplit("/", 1)[-1]
            asked.append(handle)
            if fail and handle in fail:
                raise RuntimeError("unreachable")

            class Response:
                text = pages.get(handle, "<html></html>")

            return Response()

        monkeypatch.setattr(module, "request_with_retry", fake_request)
        monkeypatch.setattr(module, "FETCH_DELAY_SECONDS", 0.0)
        return asked

    async def test_an_unreachable_channel_is_skipped_not_fatal(self, monkeypatch):
        from app.services.telegram_scout import scout

        self._stub(monkeypatch, {"ikkikanal": page(post_block())}, fail={"birkanal"})
        snapshots = await scout(["@birkanal", "@ikkikanal"])

        assert [s.handle for s in snapshots] == ["ikkikanal"]

    async def test_a_private_channel_returns_nothing(self, monkeypatch):
        from app.services.telegram_scout import fetch_channel

        self._stub(monkeypatch, {"yopiqkanal": "<html>preview unavailable</html>"})
        assert await fetch_channel("yopiqkanal") is None

    async def test_names_never_reach_the_network(self, monkeypatch):
        from app.services.telegram_scout import scout

        asked = self._stub(monkeypatch, {"birkanal": page(post_block())})
        await scout(["Najot Ta'lim", "@birkanal"])

        assert asked == ["birkanal"]

    async def test_duplicates_are_read_once(self, monkeypatch):
        from app.services.telegram_scout import scout

        asked = self._stub(monkeypatch, {"birkanal": page(post_block())})
        await scout(["@birkanal", "t.me/birkanal", "BIRKANAL"])

        assert asked == ["birkanal"]

    async def test_the_channel_cap_is_respected(self, monkeypatch):
        from app.services.telegram_scout import scout

        pages = {h: page(post_block()) for h in ("birkanal", "ikkikanal", "uchkanal", "tortkanal")}
        asked = self._stub(monkeypatch, pages)
        snapshots = await scout(["@birkanal", "@ikkikanal", "@uchkanal", "@tortkanal"], limit=2)

        assert len(snapshots) == 2
        assert len(asked) == 2, "the cap must stop the fetching, not filter afterwards"
