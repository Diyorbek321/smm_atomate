"""The edit pipeline: the decisions it makes, and the tier that gates it."""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.core.plans import PLAN_CAPABILITIES
from app.models.enums import ContentType, Plan
from app.services import video_editor as ve


class TestProbeParsing:
    """ffprobe segfaults in this image, so the stream table is parsed by hand."""

    SAMPLE = """
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip.mp4':
  Duration: 00:01:14.53, start: 0.000000, bitrate: 2371 kb/s
  Stream #0:0[0x1](und): Video: h264 (High), yuv420p(tv, bt709), 1280x720 [SAR 1:1 DAR 16:9], 30 fps
  Stream #0:1[0x2](und): Audio: aac (LC), 48000 Hz, stereo, fltp, 128 kb/s
"""

    def test_reads_duration_size_and_audio(self):
        info = ve.parse_media_info(self.SAMPLE)
        assert info.duration == pytest.approx(74.53)
        assert (info.width, info.height) == (1280, 720)
        assert info.has_audio is True

    def test_silent_footage_is_detected(self):
        info = ve.parse_media_info(self.SAMPLE.replace("Audio: aac", "Data: bin_data"))
        assert info.has_audio is False

    def test_orientation(self):
        assert ve.MediaInfo(10, 1080, 1920, True).is_portrait is True
        assert ve.MediaInfo(10, 1920, 1080, True).is_portrait is False
        assert ve.MediaInfo(10, 1080, 1080, True).is_portrait is False   # square → pad


class TestSilenceHandling:
    def test_pairs_starts_with_ends(self):
        stderr = (
            "[silencedetect] silence_start: 3.0\n"
            "[silencedetect] silence_end: 6.02 | silence_duration: 3.02\n"
            "[silencedetect] silence_start: 9.1\n"
            "[silencedetect] silence_end: 11.0 | silence_duration: 1.9\n"
        )
        assert ve.parse_silences(stderr) == [(3.0, 6.02), (9.1, 11.0)]

    def test_an_unterminated_silence_is_ignored(self):
        assert ve.parse_silences("silence_start: 4.0\n") == []

    def test_segments_are_the_gaps_between_silences(self):
        segments = ve.keep_segments(14.0, [(3.0, 6.0), (9.0, 11.0)])
        assert len(segments) == 3
        assert segments[0][0] == 0.0
        assert segments[-1][1] == 14.0
        # every kept span sits outside the silences, give or take the padding
        assert all(end > start for start, end in segments)

    def test_padding_keeps_the_breath_around_speech(self):
        [(_, first_end), *_] = ve.keep_segments(14.0, [(3.0, 6.0), (9.0, 11.0)])
        assert first_end == pytest.approx(3.0 + ve.SILENCE_PAD_SEC)

    def test_refuses_to_gut_the_clip(self):
        """Mostly-silent footage is B-roll, not a bad take."""
        assert ve.keep_segments(20.0, [(1.0, 18.0)]) == []

    def test_refuses_when_too_little_would_remain(self):
        assert ve.keep_segments(6.0, [(2.0, 5.5)]) == []

    def test_nothing_to_cut_returns_nothing(self):
        assert ve.keep_segments(12.0, []) == []

    def test_zero_length_input(self):
        assert ve.keep_segments(0.0, [(1.0, 2.0)]) == []


class TestFilterGraphs:
    def test_portrait_is_cropped_not_padded(self):
        graph = ve.reframe_filter(ve.MediaInfo(10, 1080, 1920, True))
        assert "crop=1080:1920" in graph
        assert "gblur" not in graph

    def test_landscape_gets_a_blurred_backdrop(self):
        graph = ve.reframe_filter(ve.MediaInfo(10, 1920, 1080, True))
        assert "gblur" in graph and "overlay=" in graph

    def test_trim_graph_concatenates_every_segment(self):
        graph = ve.trim_filter([(0.0, 3.0), (6.0, 9.0)], with_audio=True)
        assert graph.count("[0:v]trim=start=") == 2      # "atrim" also contains "trim"
        assert graph.count("[0:a]atrim=start=") == 2
        assert "concat=n=2:v=1:a=1[tv][ta]" in graph

    def test_trim_graph_without_audio_omits_the_audio_leg(self):
        graph = ve.trim_filter([(0.0, 3.0)], with_audio=False)
        assert "atrim" not in graph
        assert "concat=n=1:v=1:a=0[tv]" in graph

    def test_audio_chain_normalises_loudness(self):
        assert "loudnorm" in ve.audio_filter()


class TestSubtitles:
    SEGMENTS = [
        {"start": 0.4, "end": 3.0, "text": "Assalomu alaykum"},
        {"start": 3.2, "end": 6.0, "text": "Sentyabr qabuli boshlandi"},
    ]

    def test_builds_one_dialogue_per_segment(self):
        ass = ve.build_ass(self.SEGMENTS, {"accent": "#C9A227", "primary": "#141414"})
        assert ass.count("Dialogue:") == 2
        assert "[Script Info]" in ass and "Style: Brand" in ass

    def test_uses_the_brand_accent(self):
        ass = ve.build_ass(self.SEGMENTS, {"accent": "#C9A227", "primary": "#141414"})
        assert "&H0027A2C9" in ass          # ASS stores colours as BBGGRR

    def test_empty_segments_are_dropped(self):
        ass = ve.build_ass([{"start": 0, "end": 1, "text": "   "}], {})
        assert "Dialogue:" not in ass

    def test_a_missing_end_time_still_shows(self):
        ass = ve.build_ass([{"start": 2.0, "end": 0.0, "text": "salom"}], {})
        assert "0:00:02.00,0:00:03.40" in ass

    def test_timestamps_are_ass_formatted(self):
        assert ve._ass_time(3661.5) == "1:01:01.50"
        assert ve._ass_time(-4) == "0:00:00.00"


class TestPlanGate:
    def test_editing_starts_at_standard(self):
        assert PLAN_CAPABILITIES[Plan.START].video_editing is False
        assert PLAN_CAPABILITIES[Plan.STANDARD].video_editing is True
        assert PLAN_CAPABILITIES[Plan.PRO].video_editing is True

    def test_generated_clips_stay_pro_only(self):
        """Editing the client's footage is not the same as rendering our own."""
        standard = PLAN_CAPABILITIES[Plan.STANDARD]
        assert standard.video_editing is True and standard.video is False

    def test_the_edited_post_type_follows_the_same_tiers(self):
        assert ContentType.VIDEO_POST not in PLAN_CAPABILITIES[Plan.START].content_types
        assert ContentType.VIDEO_POST in PLAN_CAPABILITIES[Plan.STANDARD].content_types
        assert ContentType.VIDEO_POST in PLAN_CAPABILITIES[Plan.PRO].content_types

    def test_strategist_never_plans_an_edited_video(self):
        """It only exists once the owner actually sends footage."""
        from app.models.enums import PILLAR_CONTENT_TYPES

        planned = {t for types in PILLAR_CONTENT_TYPES.values() for t in types}
        assert ContentType.VIDEO_POST not in planned


class TestUploadLimits:
    def test_cloud_api_caps_at_20mb(self, monkeypatch):
        from app.bot.handlers import video as handler
        from app.core.config import settings

        monkeypatch.setattr(settings, "telegram_api_base", "", raising=False)
        assert handler.download_limit() == 20 * 1024 * 1024

    def test_a_local_server_lifts_the_cap(self, monkeypatch):
        from app.bot.handlers import video as handler
        from app.core.config import settings

        monkeypatch.setattr(settings, "telegram_api_base", "http://telegram-api:8081", raising=False)
        assert handler.download_limit() == 2 * 1024 * 1024 * 1024


class TestTranscriptCorrection:
    """Whisper's Uzbek needs proof-reading; the timings must survive it."""

    SEGMENTS = [
        {"start": 0.0, "end": 2.0, "text": "Nega adamlar?"},
        {"start": 2.1, "end": 5.0, "text": "Gelecekte nima ozgeradi degan sawarlar"},
    ]

    def test_reads_a_numbered_reply(self):
        parsed = ve.parse_corrections("1. Nega odamlar?\n2. Kelajakda nima o'zgaradi degan savollar", 2)
        assert parsed == ["Nega odamlar?", "Kelajakda nima o'zgaradi degan savollar"]

    def test_accepts_other_numbering_styles(self):
        assert ve.parse_corrections("1) bir\n2: ikki", 2) == ["bir", "ikki"]

    def test_a_short_reply_is_rejected(self):
        assert ve.parse_corrections("1. bir", 2) is None

    def test_out_of_range_numbers_are_rejected(self):
        assert ve.parse_corrections("1. bir\n7. yetti", 2) is None

    def test_prose_around_the_list_is_ignored(self):
        reply = "Mana tuzatilgan matn:\n1. bir\n2. ikki\nTayyor."
        assert ve.parse_corrections(reply, 2) == ["bir", "ikki"]

    async def test_timings_are_preserved(self, monkeypatch):
        class FakeResult:
            text = "1. Nega odamlar?\n2. Kelajakda nima o'zgaradi degan savollar"

        class FakeLLM:
            async def generate_text(self, *args, **kwargs):
                return FakeResult()

        monkeypatch.setattr("app.services.llm.get_llm", lambda: FakeLLM())
        fixed = await ve.correct_transcript(list(self.SEGMENTS))

        assert [s["text"] for s in fixed] == [
            "Nega odamlar?",
            "Kelajakda nima o'zgaradi degan savollar",
        ]
        assert [(s["start"], s["end"]) for s in fixed] == [(0.0, 2.0), (2.1, 5.0)]

    async def test_a_misaligned_reply_leaves_the_transcript_alone(self, monkeypatch):
        class FakeResult:
            text = "1. faqat bitta satr"

        class FakeLLM:
            async def generate_text(self, *args, **kwargs):
                return FakeResult()

        monkeypatch.setattr("app.services.llm.get_llm", lambda: FakeLLM())
        assert await ve.correct_transcript(list(self.SEGMENTS)) == self.SEGMENTS

    async def test_an_llm_failure_leaves_the_transcript_alone(self, monkeypatch):
        class FakeLLM:
            async def generate_text(self, *args, **kwargs):
                raise RuntimeError("quota exhausted")

        monkeypatch.setattr("app.services.llm.get_llm", lambda: FakeLLM())
        assert await ve.correct_transcript(list(self.SEGMENTS)) == self.SEGMENTS

    async def test_other_languages_are_left_to_whisper(self, monkeypatch):
        def explode():
            raise AssertionError("the LLM must not be called for non-Uzbek")

        monkeypatch.setattr("app.services.llm.get_llm", explode)
        assert await ve.correct_transcript(list(self.SEGMENTS), language="ru") == self.SEGMENTS


class TestReviewCard:
    """An edited clip has to arrive as a clip, not as its thumbnail."""

    class FakeBot:
        def __init__(self):
            self.calls = []

        async def send_video(self, chat_id, **kwargs):
            self.calls.append(("send_video", kwargs))
            return type("M", (), {"message_id": 11})()

        async def send_photo(self, chat_id, **kwargs):
            self.calls.append(("send_photo", kwargs))
            return type("M", (), {"message_id": 12})()

        async def send_message(self, chat_id, text, **kwargs):
            self.calls.append(("send_message", {"text": text}))
            return type("M", (), {"message_id": 13})()

    def _item(self, tmp_path, monkeypatch, *, with_video: bool):
        import uuid
        from datetime import UTC, datetime

        from app.core.config import settings
        from app.models.content_item import ContentItem
        from app.models.enums import ContentPillar, ContentType, Platform

        monkeypatch.setattr(settings, "media_root", tmp_path, raising=False)
        monkeypatch.setattr(settings, "public_base_url", "http://localhost:8000", raising=False)
        (tmp_path / "poster.jpg").write_bytes(b"JPG")
        if with_video:
            (tmp_path / "clip.mp4").write_bytes(b"MP4")

        return ContentItem(
            id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            content_type=ContentType.VIDEO_POST if with_video else ContentType.FEED_POST,
            pillar=ContentPillar.SOCIAL_PROOF,
            platform=Platform.TELEGRAM,
            topic="Dars lahzasi", headline="Dars lahzasi", hook="", cta="",
            caption_tg="matn", caption_ig="matn", hashtags=[],
            quality_score=9.0, editor_report={}, options={}, script={}, carousel_slides=[],
            scheduled_at=datetime(2026, 8, 24, 9, 0, tzinfo=UTC),
            image_url="http://localhost:8000/media/poster.jpg",
            video_url="http://localhost:8000/media/clip.mp4" if with_video else None,
        )

    async def test_a_clip_is_sent_as_video(self, tmp_path, monkeypatch):
        from app.bot.review import send_item_for_review
        from app.models.business import Business
        from app.models.enums import Plan

        bot = self.FakeBot()
        item = self._item(tmp_path, monkeypatch, with_video=True)
        await send_item_for_review(bot, item, Business(name="X", plan=Plan.PRO, settings={}), 1)

        assert [name for name, _ in bot.calls] == ["send_video"]
        assert bot.calls[0][1]["supports_streaming"] is True
        assert bot.calls[0][1]["reply_markup"] is not None      # buttons survive

    async def test_a_still_post_still_goes_as_a_photo(self, tmp_path, monkeypatch):
        from app.bot.review import send_item_for_review
        from app.models.business import Business
        from app.models.enums import Plan

        bot = self.FakeBot()
        item = self._item(tmp_path, monkeypatch, with_video=False)
        await send_item_for_review(bot, item, Business(name="X", plan=Plan.PRO, settings={}), 1)

        assert [name for name, _ in bot.calls] == ["send_photo"]


class TestBotSessionTimeout:
    """Uploading an edited clip must not die on aiogram's 60-second default."""

    def test_the_upload_window_is_generous(self):
        from app.bot.main import UPLOAD_TIMEOUT_SEC, create_bot

        bot = create_bot("123:ABC")
        assert bot.session.timeout == UPLOAD_TIMEOUT_SEC
        assert UPLOAD_TIMEOUT_SEC >= 600     # 20 MB at ~50 KB/s

    def test_the_official_api_is_the_default(self):
        from app.bot.main import create_bot

        assert "api.telegram.org" in create_bot("123:ABC").session.api.base

    def test_a_self_hosted_server_is_used_when_configured(self, monkeypatch):
        from app.bot.main import create_bot
        from app.core.config import settings

        monkeypatch.setattr(settings, "telegram_api_base", "http://telegram-api:8081", raising=False)
        session = create_bot("123:ABC").session
        assert session.api.base.startswith("http://telegram-api:8081")
        assert session.api.is_local is True
        assert session.timeout >= 600


class TestWordTimings:
    """Whisper returns a flat word list; it has to land on the right segment."""

    SEGMENTS: ClassVar[list[dict]] = [
        {"start": 0.0, "end": 2.0, "text": "salom bugun"},
        {"start": 2.0, "end": 4.0, "text": "yaxshimisiz"},
    ]

    def test_words_land_on_the_segment_that_contains_them(self):
        from app.services.transcription import attach_words

        segments = [dict(s) for s in self.SEGMENTS]
        placed = attach_words(
            segments,
            [
                {"word": "salom", "start": 0.1, "end": 0.6},
                {"word": "bugun", "start": 0.7, "end": 1.4},
                {"word": "yaxshimisiz", "start": 2.2, "end": 3.1},
            ],
        )
        assert placed == 3
        assert [w["word"] for w in segments[0]["words"]] == ["salom", "bugun"]
        assert [w["word"] for w in segments[1]["words"]] == ["yaxshimisiz"]

    def test_a_word_outside_every_segment_is_dropped_not_misplaced(self):
        from app.services.transcription import attach_words

        segments = [dict(s) for s in self.SEGMENTS]
        assert attach_words(segments, [{"word": "keyin", "start": 9.0, "end": 9.4}]) == 0

    def test_no_words_is_not_an_error(self):
        from app.services.transcription import attach_words

        assert attach_words([dict(s) for s in self.SEGMENTS], []) == 0


class TestKaraokeCaptions:
    """Each word turns brand-coloured as it is spoken."""

    WORDS = "salom bugun sizga backend dasturlash haqida gapiraman".split()

    def _segment(self, *, timed: bool = True) -> dict:
        segment = {"start": 0.0, "end": 3.5, "text": " ".join(self.WORDS)}
        if timed:
            segment["words"] = [
                {"word": word, "start": 0.5 * i, "end": 0.5 * i + 0.4}
                for i, word in enumerate(self.WORDS)
            ]
        return segment

    @staticmethod
    def _dialogue(ass: str) -> list[str]:
        return [line for line in ass.splitlines() if line.startswith("Dialogue")]

    def test_one_cue_per_spoken_word(self):
        ass = ve.build_ass([self._segment()], {"accent": "#C9A227"})
        assert len(self._dialogue(ass)) == len(self.WORDS)

    def test_only_the_spoken_word_wears_the_accent(self):
        first = self._dialogue(ve.build_ass([self._segment()], {"accent": "#C9A227"}))[0]
        # ASS reverses the channel order: C9A227 -> 27A2C9.
        assert first.count("&H27A2C9&") == 1
        assert "{\\c&H27A2C9&}salom{\\c&HFFFFFF&}" in first

    def test_the_highlight_moves_forward(self):
        cues = self._dialogue(ve.build_ass([self._segment()], {"accent": "#C9A227"}))
        assert "}salom{" in cues[0]
        assert "}bugun{" in cues[1]

    def test_cues_are_continuous_so_the_caption_never_blinks(self):
        cues = self._dialogue(ve.build_ass([self._segment()], {"accent": "#C9A227"}))
        ends = [line.split(",")[2] for line in cues]
        starts = [line.split(",")[1] for line in cues]
        assert ends[:-1] == starts[1:]

    def test_karaoke_can_be_turned_off(self):
        ass = ve.build_ass([self._segment()], {"accent": "#C9A227"}, karaoke=False)
        assert len(self._dialogue(ass)) < len(self.WORDS)
        assert "&H27A2C9&" not in ass

    def test_untimed_speech_is_shown_without_a_highlight(self):
        """A highlight on the wrong word is worse than no highlight."""
        ass = ve.build_ass([self._segment(timed=False)], {"accent": "#C9A227"})
        assert "&H27A2C9&" not in ass
        assert self._dialogue(ass)

    def test_a_corrected_transcript_that_no_longer_matches_loses_the_highlight(self):
        segment = self._segment()
        segment["text"] = "salom bugun"          # proof-reading merged words
        ass = ve.build_ass([segment], {"accent": "#C9A227"})
        assert "&H27A2C9&" not in ass

    def test_the_caption_shows_the_corrected_spelling_not_whisper_s(self):
        segment = self._segment()
        segment["text"] = segment["text"].replace("salom", "assalom")
        ass = ve.build_ass([segment], {"accent": "#C9A227"})
        assert "assalom" in ass

    def test_a_long_sentence_keeps_every_word(self):
        """The old two-line clamp silently threw the tail of a sentence away."""
        ass = ve.build_ass([self._segment()], {"accent": "#C9A227"})
        for word in self.WORDS:
            assert word in ass

    def test_braces_in_speech_cannot_open_an_override_block(self):
        """The colour name may survive as inert text; the braces may not."""
        segment = {"start": 0.0, "end": 1.0, "text": "{\\c&HFF0000&}qizil"}
        cue = ve.build_ass([segment], {"accent": "#C9A227"}).splitlines()[-1]
        assert cue.startswith("Dialogue")
        assert "{" not in cue.split(",,", 1)[1]


class TestCaptionLayout:
    #: A deterministic stand-in for the font metrics: one unit per character.
    MEASURE = staticmethod(len)

    def test_words_wrap_into_two_line_chunks(self):
        words = [{"word": "salom", "start": i, "end": i + 0.4} for i in range(12)]
        chunks = ve.layout_words(words, box=12, max_lines=2, measure=self.MEASURE)
        assert len(chunks) > 1
        assert all(len(chunk) <= 2 for chunk in chunks)

    def test_every_word_survives_the_layout(self):
        words = [{"word": f"w{i}", "start": i, "end": i + 0.4} for i in range(20)]
        laid_out = [w for chunk in ve.layout_words(words) for line in chunk for w in line]
        assert len(laid_out) == 20

    def test_blank_tokens_are_skipped(self):
        words = [{"word": " ", "start": 0, "end": 1}, {"word": "salom", "start": 1, "end": 2}]
        assert sum(len(line) for chunk in ve.layout_words(words) for line in chunk) == 1
