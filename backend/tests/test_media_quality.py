"""What leaves the system has to survive the platform's own re-encode.

These lock in the decisions that are invisible in a code review but obvious on
a phone: colour tags, a bitrate ceiling, a soundtrack, a smooth zoom, and the
sampler each tier pays for.
"""

from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path
from typing import ClassVar

import pytest
from PIL import Image

from app.core.plans import PLAN_CAPABILITIES
from app.models.enums import Plan
from app.services import encoding, video
from app.services.image_gen import DEFAULT_NEGATIVE, model_params, with_constraints
from app.services.music import MusicSpec, render_bed, write_wav
from app.services.renderer import SUPERSAMPLE, _downsample


class TestDeliveryEncoding:
    def test_colour_is_tagged_bt709(self):
        """An untagged stream is guessed at as BT.601 and arrives washed out."""
        args = encoding.video_args()
        for flag in ("-colorspace", "-color_primaries", "-color_trc"):
            assert args[args.index(flag) + 1] == "bt709"
        assert args[args.index("-color_range") + 1] == "tv"

    def test_a_keyframe_every_two_seconds(self):
        args = encoding.video_args(fps=30)
        assert args[args.index("-g") + 1] == "60"

    def test_bitrate_is_capped_so_a_clip_stays_sendable(self):
        args = encoding.video_args(maxrate="5M", bufsize="10M")
        assert args[args.index("-maxrate") + 1] == "5M"
        assert args[args.index("-bufsize") + 1] == "10M"

    def test_intermediates_are_near_lossless_and_uncapped(self):
        """Three encodes stack their losses; only the last one is delivery."""
        args = encoding.intermediate_video_args()
        assert int(args[args.index("-crf") + 1]) == encoding.INTERMEDIATE_CRF
        assert "-maxrate" not in args
        assert int(args[args.index("-crf") + 1]) < encoding.settings.video_crf

    def test_audio_is_stereo_48k(self):
        args = encoding.audio_args()
        assert args[args.index("-ar") + 1] == "48000"
        assert args[args.index("-ac") + 1] == "2"


class TestClipSoundtrack:
    """A promo that plays silent reads as unfinished."""

    def test_bed_is_written_for_the_clip_length(self, tmp_path):
        path = video.write_music_bed(tmp_path / "bed.wav", 4.0)
        assert path is not None
        with wave.open(str(path)) as handle:
            assert handle.getnchannels() == 2
            assert handle.getframerate() == 44100
            assert handle.getnframes() / handle.getframerate() == pytest.approx(4.0, abs=0.6)

    def test_a_failed_synth_never_fails_the_render(self, tmp_path, monkeypatch):
        monkeypatch.setattr(video, "render_bed", lambda *a, **k: 1 / 0)
        assert video.write_music_bed(tmp_path / "bed.wav", 4.0) is None

    def test_write_wav_scales_a_hot_signal_down(self, tmp_path):
        write_wav([2.0, -2.0, 0.0], tmp_path / "loud.wav", ceiling=0.5)
        with wave.open(str(tmp_path / "loud.wav")) as handle:
            frames = handle.readframes(handle.getnframes())
        peak = max(abs(int.from_bytes(frames[i : i + 2], "little", signed=True)) for i in (0, 2, 4))
        assert peak <= int(0.5 * 32000) + 1

    def test_the_bed_fades_out_instead_of_stopping_mid_note(self):
        bed = render_bed(MusicSpec(seconds=3.0))
        tail = bed[int(2.95 * 44100) : int(3.0 * 44100)]
        assert max(abs(value) for value in tail) < 0.05


class TestBedVariety:
    """Every clip the system made played the same four chords in the same key.

    `music.py` had the levers all along — four progressions, a transpose, a
    rotation, a shaker seed — and `promo.py` used them. The other three render
    paths (the Reels editor, the clip renderer, the kinetic engine) constructed
    a bare `MusicSpec`, took the defaults, and produced a bed that was
    byte-for-byte the same for every business and every topic.
    """

    SUBJECTS: ClassVar[list[str]] = [
        "START tarif imkoniyatlari",
        "Klinikalar uchun kadr yo'riqnomasi",
        "AI yozgan matnlar nega jonli chiqadi",
        "Backend dasturlash kursi",
    ]

    @staticmethod
    def _digest(spec) -> bytes:
        bed = render_bed(spec)
        return bytes(bed.left) + bytes(bed.right)

    def test_two_topics_do_not_share_a_bed(self):
        from app.services.music import bed_spec

        beds = {
            subject: self._digest(bed_spec(9.0, signature="Postchi", subject=subject))
            for subject in self.SUBJECTS
        }
        assert len(set(beds.values())) == len(self.SUBJECTS)

    def test_the_same_topic_always_sounds_the_same(self):
        """Otherwise a re-render is a different video, and reviews mean nothing."""
        from app.services.music import bed_spec

        once = bed_spec(9.0, signature="Postchi", subject="START tarif")
        twice = bed_spec(9.0, signature="Postchi", subject="START tarif")
        assert (once.mood, once.key_shift, once.rotation, once.seed, once.bpm) == (
            twice.mood, twice.key_shift, twice.rotation, twice.seed, twice.bpm
        )

    def test_a_business_keeps_one_key_across_its_clips(self):
        from app.services.music import bed_spec

        shifts = {bed_spec(4.0, signature="Postchi", subject=s).key_shift for s in self.SUBJECTS}
        assert len(shifts) == 1

    def test_two_businesses_do_not_share_a_key(self):
        """The two on this deployment collided under the old `sum(ord)` hash."""
        from app.services.music import key_shift_for

        assert key_shift_for("Postchi") != key_shift_for("Shanghai School")

    def test_the_key_stays_in_a_range_a_phone_can_play(self):
        from app.services.music import key_shift_for

        names = ["Postchi", "Shanghai School", "Bright Academy", "IT Park", "", "  "]
        assert all(-3 <= key_shift_for(n) <= 3 for n in names)

    def test_the_levers_are_independent(self):
        """Taken from one remainder, two subjects that agreed mod 64 came out
        with the same progression, opening bar *and* shaker at once."""
        from app.services.music import bed_spec

        specs = [bed_spec(4.0, subject=f"mavzu raqami {i}") for i in range(60)]
        assert len({s.mood for s in specs}) > 1
        assert len({s.rotation for s in specs}) > 1
        assert len({s.seed for s in specs}) > 4

    def test_a_fingerprint_does_not_move_between_processes(self):
        """`hash()` is salted per run; the worker and the API must agree."""
        from app.services.music import _fingerprint

        assert _fingerprint("Postchi") == 2679697049859725476

    def test_no_subject_still_gives_the_bed_the_defaults_always_gave(self):
        from app.services.music import MusicSpec, bed_spec

        derived = bed_spec(3.0)
        assert (derived.mood, derived.key_shift, derived.rotation, derived.seed) == (
            "calm", 0, 0, 7,
        )
        assert self._digest(derived) == self._digest(MusicSpec(seconds=3.0, bpm=derived.bpm))

    def test_the_clip_renderer_varies_its_bed(self, tmp_path):
        first = video.write_music_bed(
            tmp_path / "a.wav", 4.0, signature="Postchi", subject="START tarif"
        )
        second = video.write_music_bed(
            tmp_path / "b.wav", 4.0, signature="Postchi", subject="Klinikalar uchun kadr"
        )
        assert first and second
        assert first.read_bytes() != second.read_bytes()

    def test_the_reels_editor_varies_its_bed(self, tmp_path):
        from app.services.video_editor import _write_music

        _write_music(tmp_path / "a.wav", 4.0, signature="Postchi", subject="START tarif")
        _write_music(tmp_path / "b.wav", 4.0, signature="Postchi", subject="Klinikalar uchun kadr")
        assert (tmp_path / "a.wav").read_bytes() != (tmp_path / "b.wav").read_bytes()

    def test_the_kinetic_engine_is_timed_against_the_tempo_it_plays(self):
        """Cuts snap to `spec.bpm`; if the bed picked its own the edit drifts."""
        from app.services.music import MOOD_TEMPO, bed_spec, energy_for, mood_for

        for subject in self.SUBJECTS:
            mood = mood_for(subject)
            spec = bed_spec(
                9.0, signature="Postchi", subject=subject,
                bpm=MOOD_TEMPO[mood], energy=energy_for(mood),
            )
            assert spec.bpm == MOOD_TEMPO[mood]
            assert spec.mood == mood


class TestClipCommand:
    """The ffmpeg command is the product here, so assert on the command."""

    @staticmethod
    def _capture(monkeypatch) -> list[list[str]]:
        seen: list[list[str]] = []

        class _Process:
            returncode = 0

            async def communicate(self):
                return b"", b""

        async def fake_exec(*command, **kwargs):
            seen.append(list(command))
            return _Process()

        monkeypatch.setattr(video.asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(video, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
        return seen

    def test_the_zoom_runs_above_delivery_resolution(self, monkeypatch, tmp_path):
        """zoompan steps in whole input pixels; a 1x input jerks visibly."""
        seen = self._capture(monkeypatch)
        target = tmp_path / "out.mp4"
        target.write_bytes(b"")
        monkeypatch.setattr(Path, "read_bytes", lambda self: b"clip")
        asyncio.run(video.render_clip(tmp_path / "bg.jpg", b"png", duration=4))
        chain = seen[0][seen[0].index("-filter_complex") + 1]
        assert f"scale={video.WIDTH * video.ZOOM_SUPERSAMPLE}" in chain
        assert video.ZOOM_SUPERSAMPLE >= 2

    def test_the_clip_carries_audio(self, monkeypatch, tmp_path):
        seen = self._capture(monkeypatch)
        monkeypatch.setattr(Path, "read_bytes", lambda self: b"clip")
        asyncio.run(video.render_clip(tmp_path / "bg.jpg", b"png", duration=4))
        command = seen[0]
        assert "-map" in command and "2:a" in command
        assert "aac" in command

    def test_music_can_be_turned_off(self, monkeypatch, tmp_path):
        seen = self._capture(monkeypatch)
        monkeypatch.setattr(Path, "read_bytes", lambda self: b"clip")
        asyncio.run(video.render_clip(tmp_path / "bg.jpg", b"png", duration=4, music=False))
        assert "aac" not in seen[0]


class TestProbeClip:
    SAMPLE = (
        "  Duration: 00:00:12.40, start: 0.000000, bitrate: 2371 kb/s\n"
        "  Stream #0:0[0x1](und): Video: h264 (High), yuv420p, 1080x1920, 30 fps\n"
        "  Stream #0:1[0x2](und): Audio: aac (LC), 48000 Hz, stereo\n"
    )

    def test_reads_duration_and_audio(self):
        assert video._DURATION_RE.search(self.SAMPLE)
        hours, minutes, seconds = video._DURATION_RE.search(self.SAMPLE).groups()
        assert int(hours) * 3600 + int(minutes) * 60 + float(seconds) == pytest.approx(12.40)
        assert bool(video._AUDIO_RE.search(self.SAMPLE)) is True

    def test_silent_clip_is_detected(self):
        assert video._AUDIO_RE.search(self.SAMPLE.replace("Audio: aac", "Data: bin")) is None


class TestImageQualityPerTier:
    def test_each_tier_gets_its_own_sampler(self):
        models = {plan: PLAN_CAPABILITIES[plan].image_model for plan in Plan}
        assert "schnell" in models[Plan.START]
        assert models[Plan.STANDARD] != models[Plan.START]
        assert models[Plan.PRO] != models[Plan.STANDARD]

    def test_the_cheap_model_is_the_four_step_one(self):
        assert model_params("fal-ai/flux/schnell")["num_inference_steps"] == 4

    def test_a_paying_tier_gets_a_full_sampler(self):
        assert model_params(PLAN_CAPABILITIES[Plan.STANDARD].image_model)["num_inference_steps"] > 20

    def test_an_unknown_model_is_assumed_to_be_a_good_one(self):
        assert model_params("fal-ai/some-new-model")["num_inference_steps"] > 20

    def test_png_is_requested_rather_than_the_default_jpeg(self):
        for model in ("fal-ai/flux/schnell", "fal-ai/flux/dev", "fal-ai/flux-pro/v1.1"):
            assert model_params(model)["output_format"] == "png"


class TestPromptConstraints:
    """Flux has no negative conditioning — the ban has to be in the prompt."""

    def test_the_ban_reaches_the_prompt(self):
        prompt = with_constraints("a classroom", DEFAULT_NEGATIVE)
        assert "no text" in prompt.lower()
        assert prompt.startswith("a classroom")

    def test_the_list_stays_short_because_naming_things_summons_them(self):
        prompt = with_constraints("a classroom", ",".join(f"thing{i}" for i in range(20)))
        assert prompt.count("thing") == 6

    def test_nothing_is_appended_without_a_ban(self):
        assert with_constraints("a classroom", "") == "a classroom"
        assert with_constraints("a classroom", None) == "a classroom"


class TestCardSupersampling:
    def test_a_doubled_shot_comes_back_at_delivery_size(self):
        big = Image.new("RGB", (2160, 2700), "#141414")
        buffer = io.BytesIO()
        big.save(buffer, format="PNG")
        result = Image.open(io.BytesIO(_downsample(buffer.getvalue(), 1080, 1350)))
        assert result.size == (1080, 1350)

    def test_a_correctly_sized_shot_is_left_alone(self):
        exact = Image.new("RGB", (1080, 1350), "#141414")
        buffer = io.BytesIO()
        exact.save(buffer, format="PNG")
        assert _downsample(buffer.getvalue(), 1080, 1350) == buffer.getvalue()

    def test_a_broken_shot_still_returns_something_publishable(self):
        assert _downsample(b"not a png", 1080, 1350) == b"not a png"

    def test_supersampling_is_actually_on(self):
        assert SUPERSAMPLE >= 2


class TestVisualVerdict:
    """The editor scores the words; this scores the picture."""

    def test_a_high_score_with_nothing_clipped_is_publishable(self):
        from app.services.visual_qc import VisualVerdict

        assert VisualVerdict(score=9).acceptable is True

    def test_clipped_text_is_never_acceptable_however_pretty(self):
        from app.services.visual_qc import VisualVerdict

        assert VisualVerdict(score=10, text_complete=False).acceptable is False

    def test_unreadable_contrast_is_never_acceptable(self):
        from app.services.visual_qc import VisualVerdict

        assert VisualVerdict(score=10, readable=False).acceptable is False

    def test_a_low_score_is_not_acceptable(self):
        from app.services.visual_qc import VisualVerdict

        assert VisualVerdict(score=4).acceptable is False


class TestVisualQcGate:
    @staticmethod
    async def _review(image, monkeypatch, **kwargs):
        from app.services import visual_qc

        return await visual_qc.review_image(image, **kwargs)

    def test_the_gate_can_be_switched_off(self, monkeypatch):
        from app.services import visual_qc

        monkeypatch.setattr(visual_qc.settings, "visual_qc", False)
        assert asyncio.run(visual_qc.review_image(b"png")) is None

    def test_an_empty_image_is_not_sent_anywhere(self):
        from app.services import visual_qc

        assert asyncio.run(visual_qc.review_image(b"")) is None

    def test_no_multimodal_provider_means_no_opinion(self, monkeypatch):
        """A gate that can break the pipeline is worse than no gate."""
        from app.services import visual_qc

        def boom():
            raise RuntimeError("no key")

        monkeypatch.setattr("app.services.llm.get_document_llm", boom)
        assert asyncio.run(visual_qc.review_image(b"png")) is None

    def test_the_intended_words_are_shown_to_the_reviewer(self, monkeypatch):
        """Without them "is anything cut off?" is unanswerable."""
        from app.services import visual_qc

        seen = {}

        class _Client:
            async def generate_structured_document(self, prompt, schema, **kwargs):
                seen["prompt"] = prompt
                seen["mime"] = kwargs["mime_type"]
                return schema(score=9), None

        monkeypatch.setattr("app.services.llm.get_document_llm", lambda: _Client())
        verdict = asyncio.run(
            visual_qc.review_image(b"png", expect_text="Backend dasturlash", mime_type="image/png")
        )
        assert verdict is not None and verdict.score == 9
        assert "Backend dasturlash" in seen["prompt"]
        assert seen["mime"] == "image/png"


class TestRenderRetries:
    """A rejected render is attempted once more, and the better one is kept."""

    @staticmethod
    def _request():
        from app.agents.visual import VisualRequest
        from app.models.business import Business
        from app.models.enums import BusinessCategory, ContentPillar, ContentType

        return VisualRequest(
            business=Business(name="Test", category=BusinessCategory.EDUCATION),
            knowledge=None,
            content_type=ContentType.FEED_POST,
            pillar=ContentPillar.EDUCATIONAL,
            topic="Backend dasturlash kursi",
            headline="Juda uzun sarlavha, kartaga sig'masligi mumkin, shuning uchun",
            hook="Qo'shimcha izoh matni",
        )

    def test_the_repair_matches_the_complaint(self):
        """The retry used to shorten the headline whatever was wrong with it."""
        from app.services.visual_qc import VisualVerdict
        from app.services.visual_repair import repair

        context = {"title": "x" * 80, "body": "izoh", "photo": "data:x",
                   "layout": {"title_size": 88}}

        clipped = repair(context, VisualVerdict(score=3, text_complete=False), set())
        unreadable = repair(context, VisualVerdict(score=3, readable=False), set())

        assert clipped["layout"]["title_size"] < 88, "smaller type, same words"
        assert unreadable["photo"] == "", "a contrast problem is not a length problem"

    @staticmethod
    def _wire(monkeypatch, verdicts, tmp_path):
        from app.agents import visual
        from app.services.storage import MediaStorage

        rendered: list[int] = []

        class _Renderer:
            async def render_png(self, request):
                rendered.append(len(request.context.get("title", "")))
                return b"png-bytes"

        calls = iter(verdicts)
        async def _review(image, **kwargs):
            return next(calls, None)

        monkeypatch.setattr(visual, "get_renderer", lambda: _Renderer())
        monkeypatch.setattr(visual, "review_image", _review)
        monkeypatch.setattr(visual, "get_storage", lambda: MediaStorage(tmp_path))
        return rendered

    def test_an_acceptable_card_is_rendered_once(self, monkeypatch, tmp_path):
        from app.agents.visual import VisualAgent, VisualBrief
        from app.services.visual_qc import VisualVerdict

        rendered = self._wire(monkeypatch, [VisualVerdict(score=9)], tmp_path)
        url = asyncio.run(
            VisualAgent()._render_card(
                self._request(), VisualBrief(), template="story.html", canvas="carousel"
            )
        )
        assert url and len(rendered) == 1

    def test_a_rejected_card_is_rendered_again_and_shorter(self, monkeypatch, tmp_path):
        from app.agents.visual import VisualAgent, VisualBrief
        from app.services.visual_qc import VisualVerdict

        rendered = self._wire(
            monkeypatch,
            [VisualVerdict(score=3, text_complete=False), VisualVerdict(score=9)],
            tmp_path,
        )
        warnings: list[str] = []
        url = asyncio.run(
            VisualAgent()._render_card(
                self._request(), VisualBrief(), template="story.html",
                canvas="carousel", warnings=warnings,
            )
        )
        assert url
        assert len(rendered) == 2
        assert rendered[1] == rendered[0], "the first clipping repair shrinks type, not copy"
        assert warnings == []                      # the second attempt was fine

    def test_when_both_attempts_fail_the_owner_is_told(self, monkeypatch, tmp_path):
        from app.agents.visual import VisualAgent, VisualBrief
        from app.services.visual_qc import VisualVerdict

        self._wire(
            monkeypatch,
            [
                VisualVerdict(score=3, issues=["Matn kesilgan"]),
                VisualVerdict(score=5, issues=["Kontrast past"]),
            ],
            tmp_path,
        )
        warnings: list[str] = []
        url = asyncio.run(
            VisualAgent()._render_card(
                self._request(), VisualBrief(), template="story.html",
                canvas="carousel", warnings=warnings,
            )
        )
        assert url                                  # the better of the two still ships
        assert warnings and "5/10" in warnings[0]

    def test_without_a_gate_nothing_changes(self, monkeypatch, tmp_path):
        """No multimodal provider: one render, no warning, same as before."""
        from app.agents.visual import VisualAgent, VisualBrief

        rendered = self._wire(monkeypatch, [None], tmp_path)
        warnings: list[str] = []
        url = asyncio.run(
            VisualAgent()._render_card(
                self._request(), VisualBrief(), template="story.html",
                canvas="carousel", warnings=warnings,
            )
        )
        assert url and len(rendered) == 1 and warnings == []

    def test_the_photo_retry_uses_a_different_seed(self, monkeypatch, tmp_path):
        from app.agents import visual
        from app.agents.visual import VisualAgent, VisualBrief
        from app.services.image_gen import GeneratedImage
        from app.services.visual_qc import VisualVerdict

        seeds: list[int | None] = []

        class _Generator:
            async def generate(self, prompt, **kwargs):
                seeds.append(kwargs.get("seed"))
                return GeneratedImage(
                    url=f"http://media/{len(seeds)}.png", provider="fal",
                    width=1080, height=1350, prompt=prompt,
                )

        verdicts = iter([VisualVerdict(score=2), VisualVerdict(score=8)])
        async def _review(image):
            return next(verdicts, None)

        monkeypatch.setattr(visual, "get_image_generator", lambda: _Generator())
        monkeypatch.setattr(VisualAgent, "_review_stored", staticmethod(_review))
        url = asyncio.run(
            VisualAgent()._generate_photo(self._request(), VisualBrief(image_prompt="a room"), [])
        )
        assert url == "http://media/2.png"
        assert seeds[0] is None and isinstance(seeds[1], int)

    def test_the_photo_seed_is_stable_per_topic(self):
        from app.agents.visual import _topic_seed

        assert _topic_seed("Backend kursi") == _topic_seed("Backend kursi")
        assert _topic_seed("Backend kursi") != _topic_seed("Ingliz tili")


class TestStyleDna:
    """One palette, one light, one lens — or the feed reads as a stock collage."""

    COLOURS: ClassVar[dict[str, str]] = {"bg": "#141414", "accent": "#C9A227", "text": "#F5F2EA"}

    def test_the_brand_colours_reach_the_prompt(self):
        from app.models.enums import BusinessCategory
        from app.services.style_dna import style_for

        style = style_for(BusinessCategory.EDUCATION, self.COLOURS)
        assert "#141414" in style.palette and "#C9A227" in style.palette

    def test_the_trade_decides_who_is_in_frame(self):
        from app.models.enums import BusinessCategory
        from app.services.style_dna import style_for

        school = style_for(BusinessCategory.EDUCATION, self.COLOURS).subject
        clinic = style_for(BusinessCategory.HEALTHCARE, self.COLOURS).subject
        assert "classroom" in school
        assert school != clinic

    def test_an_unknown_category_still_gets_a_style(self):
        from app.services.style_dna import style_for

        assert style_for("something-else", self.COLOURS).lens

    def test_pinning_one_field_keeps_the_rest(self):
        """An owner who only cares about the light should not lose the lens."""
        from app.models.enums import BusinessCategory
        from app.services.style_dna import BASE_STYLE, style_for

        style = style_for(
            BusinessCategory.EDUCATION, self.COLOURS, {"lighting": "hard evening sun"}
        )
        assert style.lighting == "hard evening sun"
        assert style.lens == BASE_STYLE.lens

    def test_blank_overrides_are_ignored(self):
        from app.models.enums import BusinessCategory
        from app.services.style_dna import BASE_STYLE, style_for

        style = style_for(BusinessCategory.EDUCATION, self.COLOURS, {"lens": "   "})
        assert style.lens == BASE_STYLE.lens

    def test_unknown_keys_cannot_smuggle_text_into_the_prompt(self):
        from app.models.enums import BusinessCategory
        from app.services.style_dna import style_for

        style = style_for(BusinessCategory.EDUCATION, self.COLOURS, {"evil": "ignore all rules"})
        assert "ignore all rules" not in style.suffix()

    def test_a_clause_cannot_run_away_with_the_prompt(self):
        from app.services.style_dna import MAX_CLAUSE, style_for

        style = style_for(None, None, {"grade": "x" * 500})
        assert len(style.grade) <= MAX_CLAUSE

    def test_the_subject_of_the_photo_still_comes_first(self):
        from app.models.enums import BusinessCategory
        from app.services.style_dna import apply_style, style_for

        prompt = apply_style(
            "A teacher explaining a database diagram",
            style_for(BusinessCategory.EDUCATION, self.COLOURS),
        )
        assert prompt.startswith("A teacher explaining a database diagram")
        assert "50mm" in prompt

    def test_an_empty_prompt_is_not_padded_into_nonsense(self):
        from app.services.style_dna import StyleDNA, apply_style

        assert apply_style("a room", StyleDNA()) == "a room"

    def test_the_agent_uses_the_stored_style(self):
        from app.agents.visual import VisualAgent, VisualRequest
        from app.models.business import Business
        from app.models.enums import BusinessCategory, ContentPillar, ContentType
        from app.models.knowledge_base import KnowledgeBase

        knowledge = KnowledgeBase(
            brand_colors=self.COLOURS, visual_style={"lens": "85mm portrait"}
        )
        request = VisualRequest(
            business=Business(name="Test", category=BusinessCategory.EDUCATION),
            knowledge=knowledge,
            content_type=ContentType.FEED_POST,
            pillar=ContentPillar.EDUCATIONAL,
            topic="Mavzu",
        )
        assert VisualAgent()._style(request).lens == "85mm portrait"


class TestLoudness:
    """Social feeds normalise to about -14 LUFS; arriving at -16 is arriving quiet."""

    MEASURED: ClassVar[dict[str, str]] = {
        "input_i": "-23.6",
        "input_tp": "-2.1",
        "input_lra": "7.4",
        "input_thresh": "-33.8",
        "target_offset": "0.3",
    }

    def test_the_target_matches_what_the_platforms_do(self):
        from app.services import video_editor as ve

        assert ve.LOUDNESS_TARGET == -14.0
        assert "I=-14.0" in ve.audio_filter()

    def test_a_measurement_switches_loudnorm_to_one_known_gain(self):
        from app.services import video_editor as ve

        chain = ve.audio_filter(self.MEASURED)
        assert "linear=true" in chain
        assert "measured_I=-23.6" in chain
        assert "measured_thresh=-33.8" in chain

    def test_without_a_measurement_it_still_normalises(self):
        """A failed first pass must not cost the clip its audio."""
        from app.services import video_editor as ve

        chain = ve.audio_filter(None)
        assert "loudnorm" in chain and "linear=true" not in chain

    def test_denoising_is_gentler_than_it_was(self):
        """-24 dB treated most of a phone recording as noise."""
        from app.services import video_editor as ve

        assert ve.NOISE_FLOOR_DB <= -30
        assert f"afftdn=nf={ve.NOISE_FLOOR_DB}" in ve.audio_filter()

    @staticmethod
    def _measure(monkeypatch, stderr: str):
        from app.services import video_editor as ve

        async def fake_run(command, *, stage):
            return stderr

        monkeypatch.setattr(ve, "_run", fake_run)
        monkeypatch.setattr(ve, "_binary", lambda: "/usr/bin/ffmpeg")
        return asyncio.run(ve.measure_loudness(Path("clip.mp4")))

    def test_the_json_tail_is_read_out_of_the_ffmpeg_log(self, monkeypatch):
        noise = "frame= 100 fps=0 q=-1.0 size=N/A\n[Parsed_loudnorm_0 @ 0x1] \n"
        report = (
            '{\n"input_i" : "-23.60",\n"input_tp" : "-2.10",\n"input_lra" : "7.40",\n'
            '"input_thresh" : "-33.80",\n"output_i" : "-14.00",\n"target_offset" : "0.30"\n}'
        )
        measured = self._measure(monkeypatch, noise + report)
        assert measured is not None
        assert measured["input_i"] == "-23.60"
        assert measured["target_offset"] == "0.30"

    def test_silence_measures_as_infinity_and_is_refused(self, monkeypatch):
        report = (
            '{"input_i" : "-inf", "input_tp" : "-inf", "input_lra" : "0.00", '
            '"input_thresh" : "-inf", "target_offset" : "0.00"}'
        )
        assert self._measure(monkeypatch, report) is None

    def test_a_truncated_report_is_refused(self, monkeypatch):
        assert self._measure(monkeypatch, '{"input_i" : "-23.6"') is None

    def test_a_report_missing_a_field_is_refused(self, monkeypatch):
        assert self._measure(monkeypatch, '{"input_i" : "-23.6"}') is None

    def test_no_log_at_all_is_refused(self, monkeypatch):
        assert self._measure(monkeypatch, "ffmpeg said nothing useful") is None


class TestCarouselGate:
    """A clipped inner slide is as embarrassing as a clipped cover."""

    @staticmethod
    def _request(slides: int = 3):
        from app.agents.visual import VisualRequest
        from app.models.business import Business
        from app.models.enums import BusinessCategory, ContentPillar, ContentType

        return VisualRequest(
            business=Business(name="Test", category=BusinessCategory.EDUCATION),
            knowledge=None,
            content_type=ContentType.CAROUSEL,
            pillar=ContentPillar.EDUCATIONAL,
            topic="Backend dasturlash",
            slides=[
                {
                    "index": i,
                    "title": f"Slayd {i} — ancha uzun sarlavha, sig'masligi mumkin",
                    "body": "Uzun izoh matni " * 6,
                    "bullets": ["bir", "ikki", "uch", "to'rt"],
                }
                for i in range(1, slides + 1)
            ],
        )

    @staticmethod
    def _wire(monkeypatch, tmp_path, verdicts):
        from app.agents import visual
        from app.services.storage import MediaStorage

        seen: list[str] = []

        class _Renderer:
            async def render_png(self, request):
                seen.append(request.context.get("title", ""))
                return b"png-bytes"

        pending = iter(verdicts)
        reviewed: list[bytes] = []

        async def _review(image, **kwargs):
            reviewed.append(image)
            return next(pending, None)

        monkeypatch.setattr(visual, "get_renderer", lambda: _Renderer())
        monkeypatch.setattr(visual, "review_image", _review)
        monkeypatch.setattr(visual, "get_storage", lambda: MediaStorage(tmp_path))
        return seen, reviewed

    def test_every_slide_goes_through_the_gate(self, monkeypatch, tmp_path):
        from app.agents.visual import VisualAgent, VisualBrief
        from app.services.visual_qc import VisualVerdict

        seen, reviewed = self._wire(monkeypatch, tmp_path, [VisualVerdict(score=9)] * 3)
        slides = asyncio.run(VisualAgent()._render_carousel(self._request(3), VisualBrief()))
        assert len(slides) == 3
        assert len(reviewed) == 3                  # not just the cover
        assert len(seen) == 3

    def test_a_rejected_slide_is_redrawn_shorter(self, monkeypatch, tmp_path):
        from app.agents.visual import VisualAgent, VisualBrief
        from app.services.visual_qc import VisualVerdict

        seen, _ = self._wire(
            monkeypatch,
            tmp_path,
            [VisualVerdict(score=3, text_complete=False), VisualVerdict(score=9)],
        )
        warnings: list[str] = []
        slides = asyncio.run(
            VisualAgent()._render_carousel(self._request(1), VisualBrief(), warnings)
        )
        assert slides[0]["image_url"]
        assert len(seen) == 2
        assert len(seen[1]) == len(seen[0]), "type shrinks before the copy does"
        assert warnings == []

    def test_the_warning_names_the_slide(self, monkeypatch, tmp_path):
        from app.agents.visual import VisualAgent, VisualBrief
        from app.services.visual_qc import VisualVerdict

        self._wire(
            monkeypatch,
            tmp_path,
            [
                VisualVerdict(score=3, issues=["Matn kesilgan"]),
                VisualVerdict(score=4, issues=["Matn kesilgan"]),
                VisualVerdict(score=4, issues=["Matn kesilgan"]),
            ],
        )
        warnings: list[str] = []
        asyncio.run(VisualAgent()._render_carousel(self._request(1), VisualBrief(), warnings))
        assert warnings and "slide1" in warnings[0]

    def test_a_slide_stops_being_redrawn_once_the_levers_are_spent(self, monkeypatch, tmp_path):
        """Three renders is the cap: the original plus two targeted repairs."""
        from app.agents.visual import VisualAgent, VisualBrief
        from app.services.visual_qc import VisualVerdict

        seen, _ = self._wire(
            monkeypatch, tmp_path,
            [VisualVerdict(score=2, text_complete=False)] * 6,
        )
        warnings: list[str] = []
        asyncio.run(VisualAgent()._render_carousel(self._request(1), VisualBrief(), warnings))

        assert len(seen) <= 3
        assert warnings, "the owner is told the slide never passed"


def brightness(samples) -> float:
    """Spectral-brightness proxy: mean squared first difference over energy.

    A 100 Hz sine measures ~0.0002, a 2.6 kHz sine ~0.12, white noise ~2.0.
    It needs no FFT and no numpy, neither of which the service layer has.
    """
    values = list(samples)
    energy = sum(value * value for value in values)
    if energy <= 0:
        return 0.0
    return sum((values[i] - values[i - 1]) ** 2 for i in range(1, len(values))) / energy


class TestDeliveredLoudness:
    """Everything this system synthesises leaves at the feed's own target.

    The kinetic renderer used to ship its clips at -20 LUFS: six dB under the
    posts around them, which on a phone is the difference between a clip that
    sounds produced and one that sounds like a screen recording.
    """

    def test_the_target_is_what_the_feeds_normalise_to(self):
        assert encoding.LOUDNESS_TARGET == -14.0
        assert "loudnorm=I=-14.0" in encoding.loudnorm_filter()

    def test_true_peak_leaves_room_for_the_platform_re_encode(self):
        assert encoding.TRUE_PEAK <= -1.0
        assert f"TP={encoding.TRUE_PEAK}" in encoding.loudnorm_filter()

    def test_the_video_editor_shares_the_one_definition(self):
        """Two copies of a delivery target drift; there is only one."""
        from app.services import video_editor

        assert video_editor.LOUDNESS_TARGET is encoding.LOUDNESS_TARGET
        assert video_editor.TRUE_PEAK is encoding.TRUE_PEAK

    def test_a_kinetic_clip_is_normalised_with_or_without_a_music_bed(self):
        """Both branches of the audio graph — synth-only and licensed track.

        The synth-only branch passes a first-pass measurement; the licensed
        branch cannot, because what it normalises is a mix of our track and a
        file we never measured. Both still have to normalise.
        """
        source = Path("app/services/kinetic.py").read_text()
        graph = source[source.index("if spec.music and spec.music.exists():"):]
        graph = graph[: graph.index("out_path = tmp_path")]
        assert graph.count("loudnorm_filter(") == 2
        assert "loudnorm_filter(measured=" in graph


class TestCuesAreNotHarsh:
    """Synthesised cues stack up; broadband ones stack up into fatigue.

    Each of these measured as near-white noise before the band-limiting pass,
    which is what made the clips tiring on phone speakers.
    """

    def test_the_whoosh_no_longer_sweeps_into_the_sibilance_band(self):
        from app.services.kinetic import _sfx_whoosh

        assert brightness(_sfx_whoosh()) < 0.20

    def test_the_tick_is_a_pitched_click_not_a_noise_burst(self):
        from app.services.kinetic import _sfx_tick

        assert brightness(_sfx_tick()) < 0.30

    def test_the_impact_opens_without_a_broadband_crack(self):
        from app.services.kinetic import _sfx_impact

        assert brightness(_sfx_impact()) < 0.01

    def test_no_cue_is_hot_enough_to_clip_the_mix(self):
        """The impact used to peak at 1.22 — past full scale on its own."""
        from app.services.kinetic import sfx_library

        for name, samples in sfx_library().items():
            assert max(abs(value) for value in samples) <= 1.0, name

    def test_the_hat_is_a_shaker_rather_than_white_noise(self):
        from app.services.music import _hat

        assert brightness(_hat()) < 0.60

    def test_the_master_shelves_the_top_end_and_limits_only_peaks(self):
        import array

        from app.services.kinetic import soften

        quiet = array.array("d", [0.4, -0.4] * 200)
        assert max(abs(v) for v in soften(array.array("d", quiet))) <= 0.45

        hot = array.array("d", [3.0, -3.0] * 200)
        assert max(abs(v) for v in soften(hot)) < 1.0


class TestPropRenders:
    """3D objects composite into a scene; stock photos sit on top of one."""

    @staticmethod
    def _render(tmp_path: Path, colour: tuple[int, int, int]) -> Path:
        """A prop render: a bright object on the black backing they ship with."""
        image = Image.new("RGB", (256, 256), (0, 0, 0))
        Image.Image.paste(image, Image.new("RGB", (120, 120), colour), (68, 68))
        path = tmp_path / "prop.png"
        image.save(path)
        return path

    def _renderer(self, tmp_path, colour, *, index):
        from app.services.kinetic import KineticSpec, Scene, _SceneRenderer

        spec = KineticSpec(
            scenes=[],
            colors={"bg": "#0B1220", "accent": "#2FD9C4", "text": "#F2F6F8"},
            prop_renders=[self._render(tmp_path, colour)],
        )
        return _SceneRenderer(Scene(kind="prop", text="salom"), spec, index)

    def test_a_render_is_preferred_over_a_stock_photo(self, tmp_path):
        renderer = self._renderer(tmp_path, (240, 240, 240), index=0)
        assert renderer.prop is not None
        assert renderer.prop.mode == "RGBA"

    def test_a_dark_scene_screens_the_object_on(self, tmp_path):
        """Screen keeps the object's glow spilling into a dark ground."""
        renderer = self._renderer(tmp_path, (240, 240, 240), index=0)
        assert renderer.treatment == "dark"
        assert renderer.prop_blend == "screen"

    def test_a_light_scene_does_not_screen_the_object_away(self, tmp_path):
        """Screen against near-white is a no-op — the prop would vanish."""
        renderer = self._renderer(tmp_path, (240, 240, 240), index=1)
        assert renderer.treatment == "light"
        assert renderer.prop_blend == "normal"
        #: luminance drives alpha, so the black backing is fully transparent
        assert renderer.prop.getchannel("A").getpixel((4, 4)) == 0

    def test_the_black_backing_never_survives_as_a_rectangle(self, tmp_path):
        """A corner of the source must not paint anything into the scene."""
        renderer = self._renderer(tmp_path, (240, 240, 240), index=0)
        alpha = renderer.prop.getchannel("A")
        for corner in ((2, 2), (alpha.width - 3, 2), (2, alpha.height - 3)):
            assert alpha.getpixel(corner) == 0

    def test_layout_reserves_the_visible_object_not_the_whole_square(self, tmp_path):
        """Reserving the full square collapses the text band under it."""
        from app.services.kinetic import PROP_RENDER_EXTENT

        renderer = self._renderer(tmp_path, (240, 240, 240), index=0)
        assert renderer.prop_extent < renderer.prop.height
        assert renderer.prop_extent == int(renderer.prop.height * PROP_RENDER_EXTENT)


class TestSceneTransitions:
    """A cut is hidden, but never by covering the frame in flat colour."""

    @staticmethod
    def _renderer(kind: str, index: int):
        from app.services.kinetic import KineticSpec, Scene, _SceneRenderer

        spec = KineticSpec(scenes=[], colors={"bg": "#0B1220", "accent": "#2FD9C4"})
        return _SceneRenderer(Scene(kind=kind, text="salom"), spec, index)

    def test_the_opening_scene_arrives_on_its_own(self):
        assert self._renderer("text", 0).transition == "none"

    def test_an_ordinary_cut_cross_blurs(self):
        assert self._renderer("text", 1).transition == "whip"

    def test_a_section_marker_still_gets_the_brand_wipe(self):
        """The one place a flat accent frame is the point rather than a strobe."""
        assert self._renderer("chapter", 2).transition == "wipe"

    def test_the_wipe_draws_nothing_outside_its_own_scenes(self):
        from unittest.mock import Mock

        renderer = self._renderer("text", 1)
        draw = Mock()
        renderer._wipe(draw, 0.0)
        draw.rectangle.assert_not_called()

    def test_the_cross_blur_is_short_enough_to_lose_nothing(self):
        from app.services.kinetic import FPS, WHIP_FRAMES

        assert 0.10 <= WHIP_FRAMES / FPS <= 0.25


class TestBrandPropGeneration:
    """Each business gets its own objects, generated once and reused."""

    def test_the_prompt_asks_for_the_backing_the_renderer_drops_out(self):
        """A prop on a white or furnished background cannot be composited."""
        from app.services.brand_props import NEGATIVE, PROMPT

        filled = PROMPT.format(concept="a closed padlock", accent="#37B3A2")
        assert "pure black background" in filled
        assert "#37B3A2" in filled
        for banned in ("white background", "floor", "horizon"):
            assert banned in NEGATIVE

    def test_a_topic_selects_its_own_shelf_first(self):
        from app.services.brand_props import concepts_for

        it_props = concepts_for("python backend kod", 4)
        assert all("terminal" in c or "server" in c or "node" in c or "microchip" in c
                   for c in it_props)
        assert "padlock" in concepts_for("IELTS speaking", 3)[0]

    def test_filenames_come_from_the_concept_so_a_re_run_tops_up(self):
        from app.services.brand_props import _slug

        assert _slug("a closed padlock") == _slug("A Closed Padlock")
        assert _slug("a closed padlock") != _slug("a graduation cap")

    def test_an_unconfigured_provider_is_not_an_error(self, tmp_path, monkeypatch):
        """A business with no props renders exactly as it did before."""
        from app.services import brand_props

        generator = type("Off", (), {"enabled": False})()
        result = asyncio.run(
            brand_props.ensure_props("biz", generator=generator)
        )
        assert result == []

    def test_an_existing_shelf_is_not_regenerated(self, tmp_path, monkeypatch):
        from app.services import brand_props

        folder = tmp_path / "props"
        folder.mkdir()
        for concept in brand_props.concepts_for("", 6):
            (folder / f"{brand_props._slug(concept)}.png").write_bytes(b"x")
        monkeypatch.setattr(brand_props, "props_dir", lambda _: folder)

        called = []

        async def _never(*args, **kwargs):
            called.append(args)

        monkeypatch.setattr(brand_props, "_render_one", _never)
        generator = type("On", (), {"enabled": True})()
        result = asyncio.run(brand_props.ensure_props("biz", generator=generator))
        assert called == []
        assert len(result) == 6

    def test_one_failed_render_does_not_lose_the_others(self, tmp_path, monkeypatch):
        from app.services import brand_props

        folder = tmp_path / "props"
        monkeypatch.setattr(brand_props, "props_dir", lambda _: folder)

        async def _flaky(generator, concept, accent, target):
            if "padlock" in concept:
                return None                        # provider refused this one
            target.write_bytes(b"png")
            return target

        monkeypatch.setattr(brand_props, "_render_one", _flaky)
        generator = type("On", (), {"enabled": True})()
        result = asyncio.run(
            brand_props.ensure_props("biz", topic="", count=4, generator=generator)
        )
        assert len(result) == 3


class TestSyntheticBold:
    """A display face with one weight must not be faked into a bolder one.

    Anton — the face Postchi's brand kit names — ships Regular only. Asked for
    the 800 the stylesheet wants, Chromium draws every glyph twice at an offset
    to fake it, and on a condensed face the two copies overlap into a smear.
    The visual QC gate caught it (3/10, twice) but retrying could not fix it:
    shortening the headline does not change how the glyphs are drawn.
    """

    def test_the_title_refuses_synthetic_weights(self):
        from pathlib import Path

        css = Path("app/templates/base.css").read_text(encoding="utf-8")
        # Split on the next selector, not on `}` — the rule interpolates
        # `{{ fonts.display }}`, whose closing braces would cut it short.
        title_rule = css.split(".title {", 1)[1].split(".title .hl", 1)[0]

        assert "font-synthesis: none" in title_rule
        assert "-webkit-font-synthesis: none" in title_rule

    def test_the_bundled_display_face_really_has_one_weight(self):
        """If Anton ever ships a bold, the rule above stops being load-bearing."""
        from fontTools.ttLib import TTFont

        font = TTFont("app/assets/fonts/anton.ttf")
        assert font["OS/2"].usWeightClass == 400
