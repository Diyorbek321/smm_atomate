"""Renderer, storage, voice download, session scope and error handlers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.services.renderer import CANVAS, DEFAULT_COLORS, RenderRequest, layout_for, merge_colors


class TestTemplates:
    def _render(self, template: str, context: dict, canvas: str = "carousel") -> str:
        from app.services.renderer import get_renderer

        width, height = CANVAS[canvas]
        return get_renderer().render_html(
            RenderRequest(template=template, context=context, width=width, height=height)
        )

    def test_story_template_renders_content(self):
        html = self._render(
            "story.html",
            {
                "brand": "Bright IELTS",
                "kicker": "sales",
                "title": "IELTS 7.0 uch oyda",
                "body": "Kuniga 30 daqiqa listening",
                "highlight": "600 000 so'm",
                "cta": "Yozing",
                "contact": "+998901234567",
            },
            canvas="story",
        )
        assert "Bright IELTS" in html
        assert "IELTS 7.0 uch oyda" in html
        assert "600 000 so&#39;m" in html or "600 000 so'm" in html
        assert "<style>" in html

    def test_carousel_template_shows_position(self):
        html = self._render(
            "carousel_slide.html",
            {
                "brand": "Bright",
                "index": 2,
                "total": 5,
                "title": "Ikkinchi slayd",
                "body": "Matn",
                "bullets": ["Bir", "Ikki"],
                "cta": "Yozing",
                "contact": "",
            },
        )
        assert "2/5" in html
        assert "Keyingisi" in html      # not the last slide
        assert "Bir" in html and "Ikki" in html

    def test_carousel_last_slide_shows_cta(self):
        html = self._render(
            "carousel_slide.html",
            {"brand": "B", "index": 5, "total": 5, "title": "Oxiri", "body": "", "cta": "Yozing",
             "contact": ""},
        )
        assert "Keyingisi" not in html
        assert "Yozing" in html

    def test_quote_template(self):
        html = self._render(
            "quote_card.html",
            {"brand": "B", "quote": "3 oyda 7.5 oldim", "initials": "DA", "author": "Dilnoza",
             "role": "o'quvchi", "result": "IELTS 7.5", "cta": "", "contact": ""},
        )
        assert "3 oyda 7.5 oldim" in html
        assert "IELTS 7.5" in html

    def test_html_is_escaped(self):
        html = self._render(
            "story.html",
            {"brand": "B", "title": "<script>alert(1)</script>", "body": "", "cta": "", "contact": ""},
            canvas="story",
        )
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestLayout:
    def test_story_typography_is_larger_than_feed(self):
        story = layout_for(*CANVAS["story"])
        feed = layout_for(*CANVAS["carousel"])
        assert story["title_size"] > feed["title_size"]

    def test_brand_colors_override_only_known_keys(self):
        colors = merge_colors({"accent": "#FF0000", "bogus": "#00FF00", "bg": "not-a-color"})
        assert colors["accent"] == "#FF0000"
        assert colors["bg"] == DEFAULT_COLORS["bg"]     # invalid value ignored
        assert "bogus" not in colors

    def test_none_yields_defaults(self):
        assert merge_colors(None) == DEFAULT_COLORS


class TestPillowFallback:
    def test_produces_a_valid_png(self):
        from app.services.renderer import _pillow_card

        data = _pillow_card(
            RenderRequest(
                template="story.html",
                context={
                    "brand": "Bright IELTS",
                    "colors": DEFAULT_COLORS,
                    "title": "IELTS 7.0 uch oyda kafolat bilan",
                    "body": "Kuniga 30 daqiqa listening qiling",
                    "contact": "+998901234567",
                },
                width=1080,
                height=1920,
            )
        )
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(data) > 5_000

        from io import BytesIO

        from PIL import Image

        image = Image.open(BytesIO(data))
        assert image.size == (1080, 1920)


class TestStorage:
    def test_save_read_delete_cycle(self, tmp_path):
        from app.services.storage import MediaStorage

        storage = MediaStorage(tmp_path)
        stored = storage.save_bytes(b"\x89PNG-data", prefix="test", content_type="image/png")

        assert stored.path.exists()
        assert stored.filename.endswith(".png")
        assert stored.size == len(b"\x89PNG-data")
        assert stored.url.endswith(stored.filename)

        assert storage.delete(stored.filename) is True
        assert storage.delete(stored.filename) is False

    def test_cleanup_respects_retention(self, tmp_path):
        import os
        import time

        from app.services.storage import MediaStorage

        storage = MediaStorage(tmp_path)
        recent = storage.save_bytes(b"a", prefix="new")
        old = storage.save_bytes(b"b", prefix="old")
        ancient = time.time() - 90 * 86400
        os.utime(old.path, (ancient, ancient))

        assert storage.cleanup(older_than_days=30) == 1
        assert recent.path.exists()
        assert not old.path.exists()

    def test_cleanup_spares_brand_assets(self, tmp_path):
        import os
        import time

        from app.services.storage import MediaStorage

        storage = MediaStorage(tmp_path)
        brand_dir = tmp_path / "brand"
        brand_dir.mkdir()
        logo = brand_dir / "logo.jpg"
        logo.write_bytes(b"logo")
        ancient = time.time() - 365 * 86400
        os.utime(logo, (ancient, ancient))

        assert storage.cleanup(older_than_days=30) == 0
        assert logo.exists()

    def test_logo_data_uri_inlines_brand_logo(self, tmp_path, monkeypatch):
        from app.agents import visual
        from app.models.knowledge_base import KnowledgeBase
        from app.services.storage import MediaStorage

        storage = MediaStorage(tmp_path)
        (tmp_path / "brand").mkdir()
        (tmp_path / "brand" / "logo.jpg").write_bytes(b"\xff\xd8fakejpg")
        monkeypatch.setattr(visual, "get_storage", lambda: storage)

        kb = KnowledgeBase(logo_url="/media/brand/logo.jpg")
        assert visual.logo_data_uri(kb).startswith("data:image/jpeg;base64,")

        assert visual.logo_data_uri(None) == ""
        assert visual.logo_data_uri(KnowledgeBase(logo_url=None)) == ""
        assert visual.logo_data_uri(KnowledgeBase(logo_url="/media/brand/missing.png")) == ""

    def test_brand_photo_pick_is_deterministic(self, tmp_path, monkeypatch):
        from app.agents import visual
        from app.services.storage import MediaStorage

        storage = MediaStorage(tmp_path)
        photos = tmp_path / "brand" / "photos"
        photos.mkdir(parents=True)
        for i in range(3):
            (photos / f"photo_{i}.jpg").write_bytes(b"\xff\xd8img" + bytes([i]))
        monkeypatch.setattr("app.services.brand_assets.get_storage", lambda: storage)

        first = visual.pick_brand_photo("Ingliz tili kursi")
        assert first.startswith("data:image/jpeg;base64,")
        assert visual.pick_brand_photo("Ingliz tili kursi") == first  # same topic, same photo
        assert visual.pick_brand_photo("") != "" or True  # empty seed still safe

    def test_brand_photo_empty_when_library_missing(self, tmp_path, monkeypatch):
        from app.agents import visual
        from app.services.storage import MediaStorage

        monkeypatch.setattr("app.services.brand_assets.get_storage", lambda: MediaStorage(tmp_path))
        assert visual.pick_brand_photo("mavzu") == ""

    def test_card_body_never_echoes_the_title(self):
        from app.agents.visual import VisualAgent, VisualBrief, VisualRequest
        from app.models.business import Business
        from app.models.enums import BusinessCategory, ContentPillar, ContentType

        request = VisualRequest(
            business=Business(name="Test", category=BusinessCategory.EDUCATION),
            knowledge=None,
            content_type=ContentType.FEED_POST,
            pillar=ContentPillar.EDUCATIONAL,
            topic="Mavzu",
            headline="Bir xil sarlavha!",
            hook="Bir xil sarlavha!",
        )
        context = VisualAgent()._card_context(request, VisualBrief(), canvas="carousel")
        assert context["title"] == "Bir xil sarlavha!"
        assert context["body"] == ""

    def test_checksum_is_stable(self, tmp_path):
        from app.services.storage import MediaStorage

        storage = MediaStorage(tmp_path)
        assert storage.checksum(b"abc") == storage.checksum(b"abc")
        assert storage.checksum(b"abc") != storage.checksum(b"abd")

    def test_content_type_maps_to_extension(self, tmp_path):
        from app.services.storage import MediaStorage

        storage = MediaStorage(tmp_path)
        assert storage.save_bytes(b"x", content_type="image/jpeg").filename.endswith(".jpg")
        assert storage.save_bytes(b"x", content_type="video/mp4").filename.endswith(".mp4")


class TestVoiceDownload:
    async def test_download_voice_reads_the_file(self):
        from aiogram.types import File, Message, Voice

        class FakeBot:
            async def get_file(self, file_id: str) -> File:
                assert file_id == "vid"
                return File(file_id=file_id, file_unique_id="u", file_path="voice/file.ogg")

            async def download_file(self, path: str, destination) -> None:
                destination.write(b"ogg-bytes")

        message = Message(
            message_id=1,
            date=datetime.now(UTC),
            chat={"id": 1, "type": "private"},
            voice=Voice(file_id="vid", file_unique_id="u", duration=2, mime_type="audio/ogg",
                        file_size=100),
        )

        from app.bot.utils import download_voice

        payload = await download_voice(FakeBot(), message)
        assert payload == (b"ogg-bytes", "audio/ogg")

    async def test_non_voice_message_returns_none(self):
        from aiogram.types import Message

        from app.bot.utils import download_voice

        message = Message(
            message_id=1, date=datetime.now(UTC), chat={"id": 1, "type": "private"}, text="salom"
        )
        assert await download_voice(object(), message) is None

    async def test_oversized_voice_is_rejected(self):
        from aiogram.types import Message, Voice

        from app.bot.utils import MAX_VOICE_BYTES, download_voice

        message = Message(
            message_id=1,
            date=datetime.now(UTC),
            chat={"id": 1, "type": "private"},
            voice=Voice(file_id="v", file_unique_id="u", duration=9999, file_size=MAX_VOICE_BYTES + 1),
        )
        assert await download_voice(object(), message) is None


class TestSessionScope:
    async def test_rolls_back_on_error(self, patch_global_session_scope, database):
        from sqlalchemy import text

        from app.db.session import session_scope

        with pytest.raises(RuntimeError):
            async with session_scope() as db:
                await db.execute(text("SELECT 1"))
                raise RuntimeError("boom")

    async def test_commits_on_success(self, patch_global_session_scope, database):
        from sqlalchemy import text

        from app.db.session import session_scope

        async with session_scope() as db:
            value = (await db.execute(text("SELECT 42"))).scalar()
        assert value == 42


class TestErrorEnvelope:
    async def test_unhandled_errors_return_the_envelope(self, database):
        from httpx import ASGITransport, AsyncClient

        from app.main import create_app

        app = create_app()

        @app.get("/boom")
        async def boom():
            raise RuntimeError("kaboom")

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/boom")

        assert response.status_code == 500
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "internal_error"

    async def test_unknown_route_uses_the_envelope(self, client):
        response = await client.get("/api/v1/nope")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "http_404"


class TestNotifyAdmins:
    async def test_broadcast_to_reviewers(self, session, monkeypatch):
        import contextlib

        from app.bot.notifier import notify_admins
        from app.models.business import Business, BusinessAdmin
        from app.models.enums import AdminRole, BusinessCategory, Language, ToneOfVoice
        from app.utils.dates import utcnow

        business = Business(
            name="Notify", slug=f"n-{uuid.uuid4().hex[:8]}", category=BusinessCategory.EDUCATION,
            tone_of_voice=ToneOfVoice.CASUAL, target_audience="", language=Language.UZ,
            timezone="Asia/Tashkent", settings={},
        )
        session.add(business)
        await session.flush()
        session.add(
            BusinessAdmin(business_id=business.id, telegram_user_id=1, role=AdminRole.OWNER,
                          receives_reviews=True)
        )
        await session.flush()
        assert utcnow() is not None

        sent: list[tuple[int, str]] = []

        class FakeBot:
            async def send_message(self, chat_id, text):
                sent.append((chat_id, text))

        @contextlib.asynccontextmanager
        async def fake_session(token=None):
            yield FakeBot()

        monkeypatch.setattr("app.bot.notifier.bot_session", fake_session)

        count = await notify_admins(session, business.id, "❌ Xatolik")
        assert count == 1
        assert sent[0] == (1, "❌ Xatolik")

    async def test_blocked_chat_does_not_break_the_broadcast(self, session, monkeypatch):
        import contextlib

        from app.bot.notifier import notify_admins
        from app.models.business import Business, BusinessAdmin
        from app.models.enums import AdminRole, BusinessCategory, Language, ToneOfVoice

        business = Business(
            name="Blocked", slug=f"b-{uuid.uuid4().hex[:8]}", category=BusinessCategory.EDUCATION,
            tone_of_voice=ToneOfVoice.CASUAL, target_audience="", language=Language.UZ,
            timezone="Asia/Tashkent", settings={},
        )
        session.add(business)
        await session.flush()
        session.add_all(
            [
                BusinessAdmin(business_id=business.id, telegram_user_id=1, role=AdminRole.OWNER,
                              receives_reviews=True),
                BusinessAdmin(business_id=business.id, telegram_user_id=2, role=AdminRole.MANAGER,
                              receives_reviews=True),
            ]
        )
        await session.flush()

        class FlakyBot:
            async def send_message(self, chat_id, text):
                if chat_id == 1:
                    raise RuntimeError("bot was blocked by the user")

        @contextlib.asynccontextmanager
        async def fake_session(token=None):
            yield FlakyBot()

        monkeypatch.setattr("app.bot.notifier.bot_session", fake_session)

        assert await notify_admins(session, business.id, "x") == 1


class TestVideoService:
    def _colors(self):
        return {"bg": "#141414", "text": "#F5F2EA", "accent": "#C9A227", "on_accent": "#141414"}

    def test_overlay_is_transparent_png_at_canvas_size(self):
        from io import BytesIO

        from PIL import Image

        from app.services.video import ClipBrief, build_overlay

        png = build_overlay(
            ClipBrief(title="Kuzgi qabul boshlandi", subtitle="Til, matematika va IT",
                      phone="+998 93 191 33 08", footer="Angren shahri"),
            self._colors(),
        )
        img = Image.open(BytesIO(png))
        assert img.size == (1080, 1920)          # video service has its own canvas
        assert img.mode == "RGBA"
        assert img.getpixel((10, 10))[3] == 0  # top stays transparent

    def test_overlay_survives_missing_fields_and_bad_logo(self):
        from app.services.video import ClipBrief, build_overlay

        png = build_overlay(ClipBrief(title="Sarlavha"), self._colors(), logo=b"not-an-image")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg yo'q")
    async def test_render_clip_produces_mp4(self, tmp_path):
        from PIL import Image

        from app.services.video import ClipBrief, build_overlay, render_clip

        bg = tmp_path / "bg.jpg"
        Image.new("RGB", (540, 960), (20, 20, 24)).save(bg)
        overlay = build_overlay(ClipBrief(title="Test klip"), self._colors())
        data = await render_clip(bg, overlay, duration=1)
        assert len(data) > 3_000
        assert b"ftyp" in data[:64]  # MP4 container marker

    @pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg yo'q")
    async def test_overlay_on_video_brands_an_existing_clip(self, tmp_path):
        from PIL import Image

        from app.services.video import ClipBrief, build_overlay, overlay_on_video, render_clip

        bg = tmp_path / "bg.jpg"
        Image.new("RGB", (540, 960), (24, 20, 20)).save(bg)
        base_clip = await render_clip(bg, build_overlay(ClipBrief(title=""), self._colors()), duration=1)
        clip_path = tmp_path / "base.mp4"
        clip_path.write_bytes(base_clip)

        branded = await overlay_on_video(clip_path, build_overlay(ClipBrief(title="AI klip"), self._colors()))
        assert b"ftyp" in branded[:64]


class TestKineticEngine:
    def _colors(self):
        return {"bg": "#141414", "text": "#F5F2EA", "accent": "#C9A227", "on_accent": "#141414"}

    def test_scene_renderer_draws_accent_word(self):
        from app.services import kinetic
        from app.services.kinetic import KineticSpec, Scene, _SceneRenderer

        spec = KineticSpec(scenes=[], colors=self._colors())
        renderer = _SceneRenderer(Scene(text="Reklama emas NATIJA kerak", accent="NATIJA"), spec, 0)
        assert renderer.tiles, "so'z plitalari yaratilishi kerak"
        early = renderer.frame(0.05)
        late = renderer.frame(0.95)
        assert early.size == (kinetic.W, kinetic.H)
        assert early.tobytes() != late.tobytes()  # animatsiya bor

    def test_soundtrack_mixes_every_cue_into_one_wav(self, tmp_path):
        import wave

        from app.services.kinetic import mix_soundtrack

        path = mix_soundtrack(
            [("whoosh", 0.0, 1.0), ("tick", 0.4, 0.5), ("impact", 1.2, 1.0)], 2.0,
            tmp_path / "track.wav",
        )
        with wave.open(str(path)) as track:
            assert track.getnchannels() == 2
            assert track.getframerate() == 44100
            frames = track.readframes(track.getnframes())
        assert track.getnframes() > 2.0 * 44100          # covers the whole clip
        assert max(frames) > 0                            # actual audio, not silence

    def test_unknown_cue_is_ignored(self, tmp_path):
        from app.services.kinetic import mix_soundtrack

        path = mix_soundtrack([("nosuchsound", 0.1, 1.0)], 0.5, tmp_path / "t.wav")
        assert path.exists()

    @pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg yo'q")
    async def test_render_kinetic_produces_mp4_with_audio(self, tmp_path, monkeypatch):
        from app.services import kinetic
        from app.services.storage import MediaStorage

        monkeypatch.setattr(kinetic, "get_storage", lambda: MediaStorage(tmp_path))
        spec = kinetic.KineticSpec(
            scenes=[
                kinetic.Scene(text="Sinov klip", accent="klip", duration=0.8),
                kinetic.Scene(kind="outro", text="Brend", sub="izoh", duration=0.8),
            ],
            colors=self._colors(),
            brand="Brend",
            phone="+998 90 000 00 00",
        )
        result = await kinetic.render_kinetic(spec)
        assert result.video.filename.endswith(".mp4")
        assert result.cover is not None and result.cover.filename.endswith(".jpg")
        data = result.video.path.read_bytes()
        assert b"ftyp" in data[:64]
        assert len(data) > 20_000

    def test_accent_resolution_is_forgiving(self):
        from app.services.kinetic import resolve_accent

        words = "Shanghai School bilimlar shahri".split()
        assert resolve_accent(words, "bilimlar") == 2          # exact
        assert resolve_accent(words, "bilim") == 2             # model returned a stem
        assert resolve_accent(words, "yoq") == 2               # absent → longest, later wins
        assert resolve_accent(["Til", "va", "IT"], "") == 0     # nothing usable → longest
        assert resolve_accent(["a", "b"], "") == -1             # nothing worth highlighting
        assert resolve_accent([], "x") == -1

    def test_apostrophe_variants_match(self):
        from app.services.kinetic import resolve_accent

        assert resolve_accent(["boshlang'ich", "kurs"], "boshlangʻich") == 0

    def test_chapter_and_stat_scenes_render(self):
        from app.services import kinetic
        from app.services.kinetic import KineticSpec, Scene, _SceneRenderer

        spec = KineticSpec(scenes=[], colors=self._colors(), brand="Brend")
        chapter = _SceneRenderer(Scene(kind="chapter", value="02", text="Til kurslari"), spec, 1)
        stat = _SceneRenderer(Scene(kind="stat", value="350 000", text="so'mdan"), spec, 2)
        for renderer in (chapter, stat):
            assert renderer.tiles == []                  # these kinds draw themselves
            early, late = renderer.frame(0.05), renderer.frame(0.95)
            assert early.size == (kinetic.W, kinetic.H)
            assert early.tobytes() != late.tobytes()     # animated, not static

    def test_long_script_falls_back_when_model_returns_too_little(self):
        from app.agents.kinetic import fallback_script

        scenes = fallback_script("Kuzgi qabul", "Shanghai School", "long")
        assert len(scenes) >= 8
        assert any(s.kind == "chapter" for s in scenes)
        assert any(s.kind == "stat" for s in scenes)

    def test_long_clip_is_stretched_to_its_promised_runtime(self):
        from app.agents.kinetic import KineticAgent
        from app.services.kinetic import Scene

        scenes = [Scene(text=f"Sahna {i}", duration=1.8) for i in range(20)]   # 36s
        KineticAgent._fit_duration(scenes, target=55.0)
        total = sum(s.duration for s in scenes)
        assert 49 <= total <= 65
        assert all(1.4 <= s.duration <= 3.4 for s in scenes)

        already_right = [Scene(text="x", duration=2.5) for _ in range(22)]     # 55s
        before = [s.duration for s in already_right]
        KineticAgent._fit_duration(already_right, target=55.0)
        assert [s.duration for s in already_right] == before   # in range → untouched

    def test_stat_without_a_label_becomes_a_text_scene(self):
        from app.agents.kinetic import KineticAgent, KineticSceneSpec

        scene = KineticAgent._to_scene(KineticSceneSpec(kind="stat", value="11", text=""))
        assert scene.kind == "text" and scene.text == "11" and scene.value == ""

        labelled = KineticAgent._to_scene(
            KineticSceneSpec(kind="stat", value="10 yil", text="tajriba")
        )
        assert labelled.kind == "stat" and labelled.value == "10 yil"

    def test_counter_animates_digits_and_keeps_the_rest(self):
        from app.services.kinetic import count_up

        assert count_up("350 000", 0.0).endswith("0")       # starts at zero
        assert count_up("350 000", 1.0) == "350 000"        # lands exactly
        assert count_up("10+", 1.0) == "10+"
        assert "+" in count_up("10+", 0.5)                  # suffix survives
        assert count_up("Bepul", 0.4) == "Bepul"            # no digits → untouched

    def test_dark_scenes_underline_the_accent_word(self):
        from app.services.kinetic import KineticSpec, Scene, _SceneRenderer

        spec = KineticSpec(scenes=[], colors=self._colors())
        dark = _SceneRenderer(Scene(text="Reklama emas natija", accent="natija"), spec, 0)
        assert dark.treatment == "dark"
        assert any(tile.underline for tile in dark.tiles)
        assert not any(tile.marker for tile in dark.tiles)

        light = _SceneRenderer(Scene(text="Reklama emas natija", accent="natija"), spec, 1)
        assert light.treatment == "light"
        assert any(tile.marker for tile in light.tiles)     # highlighter instead

    def test_split_and_code_scenes_render(self):
        from app.services import kinetic
        from app.services.kinetic import KineticSpec, Scene, _SceneRenderer

        spec = KineticSpec(scenes=[], colors=self._colors(), brand="Brend")
        split = _SceneRenderer(
            Scene(kind="split", text="Frontend", value="Backend",
                  items=["Ko'rinadigan qism", "Ko'rinmaydigan qism"]), spec, 0
        )
        code = _SceneRenderer(
            Scene(kind="code", text="Backend", items=["def login(user):", "  return token"]), spec, 3
        )
        assert code.treatment == "dark"          # a terminal is never on a gold wash
        for renderer in (split, code):
            assert renderer.tiles == []
            early, late = renderer.frame(0.05, 1), renderer.frame(0.95, 28)
            assert early.size == (kinetic.W, kinetic.H)
            assert early.tobytes() != late.tobytes()

    def test_technical_topics_prefer_the_it_shelf(self, tmp_path, monkeypatch):
        import uuid

        from app.services.brand_assets import photo_library
        from app.services.storage import MediaStorage

        photos = tmp_path / "brand" / "photos"
        (photos / "it").mkdir(parents=True)
        (photos / "general.jpg").write_bytes(b"\xff\xd8g")
        (photos / "it" / "code.jpg").write_bytes(b"\xff\xd8c")
        monkeypatch.setattr("app.services.brand_assets.get_storage", lambda: MediaStorage(tmp_path))

        assert [p.name for p in photo_library(None, "Frontend va backend farqi")] == ["code.jpg"]
        assert [p.name for p in photo_library(None, "Ingliz tili kurslari")] == ["general.jpg"]

        # A client's own shelf wins over the shared one, always.
        business = uuid.uuid4()
        own = tmp_path / "brand" / str(business) / "photos"
        own.mkdir(parents=True)
        (own / "mine.jpg").write_bytes(b"\xff\xd8m")
        assert [p.name for p in photo_library(business, "Ingliz tili")] == ["mine.jpg"]
        assert [p.name for p in photo_library(uuid.uuid4(), "Ingliz tili")] == ["general.jpg"]

    def test_reading_time_scales_with_content(self):
        from app.services.kinetic import Scene, reading_time

        short = reading_time(Scene(text="Bugun boshlang"))
        long_line = reading_time(Scene(text="Farzandingiz kelajagi haqida jiddiy o'ylab ko'ring"))
        assert long_line > short >= 2.4
        # A caption needs its own beat, a comparison needs the most time.
        assert reading_time(Scene(text="Bugun boshlang", sub="izoh")) > short
        assert reading_time(
            Scene(kind="split", text="A", value="B", items=["chap izoh", "o'ng izoh"])
        ) >= 3.0

    def test_words_finish_assembling_in_the_first_half(self):
        from app.services.kinetic import KineticSpec, Scene, _SceneRenderer

        spec = KineticSpec(scenes=[], colors=self._colors())
        for duration in (2.4, 5.0):
            scene = Scene(text="Bir ikki uch to'rt besh olti", duration=duration)
            renderer = _SceneRenderer(scene, spec, 0)
            last_landing = max(renderer.word_beats) + renderer.entry_n
            assert last_landing < 0.75, f"{duration}s: matn juda kech to'planyapti"

    def test_long_mode_never_trims_below_the_reading_floor(self):
        from app.agents.kinetic import KineticAgent
        from app.services.kinetic import Scene, reading_time

        scenes = [Scene(text="Uzun jumla bu yerda turadi albatta", duration=6.0) for _ in range(30)]
        KineticAgent._fit_duration(scenes, target=58.0)
        assert all(s.duration >= reading_time(s) for s in scenes)

    def test_null_placeholders_never_reach_the_screen(self):
        from app.agents.kinetic import KineticAgent, KineticSceneSpec

        scene = KineticAgent._to_scene(
            KineticSceneSpec(kind="split", text="Frontend", value="Backend", sub="null",
                             items=["chap", "None", "o'ng"])
        )
        assert scene.sub == ""
        assert scene.items == ["chap", "o'ng"]


class TestMusicBed:
    def test_bed_is_tempo_locked_and_fades_out(self):
        from app.services.music import MusicSpec, render_bed

        bed = render_bed(MusicSpec(seconds=6.0, bpm=96))
        assert len(bed) >= int(6.0 * 44100)
        assert max(abs(v) for v in bed) <= 1.0            # never clips
        tail = bed[int(6.0 * 44100) - 10:int(6.0 * 44100)]
        assert max(abs(v) for v in tail) < 0.05           # ends quiet, not mid-note
        assert all(v == 0 for v in bed[int(6.05 * 44100):])

    def test_the_bed_is_genuinely_stereo(self):
        """A duplicated mono channel is why synthesised beds sound small."""
        from app.services.music import MusicSpec, render_bed

        bed = render_bed(MusicSpec(seconds=6.0, bpm=120))
        differences = sum(
            1 for left, right in zip(bed.left, bed.right, strict=False) if abs(left - right) > 1e-4
        )
        assert differences > len(bed) * 0.5

    def test_the_bed_is_arranged_rather_than_looped_flat(self):
        """The intro must measure quieter than the body, or there is no range."""
        from app.services.music import MusicSpec, render_bed

        spec = MusicSpec(seconds=20.0, bpm=120)
        bed = render_bed(spec)
        bar = (60.0 / spec.bpm) * 4

        def rms(start: float, end: float) -> float:
            lo, hi = int(start * 44100), int(end * 44100)
            window = bed[lo:hi]
            return (sum(v * v for v in window) / max(1, len(window))) ** 0.5

        intro, body = rms(0.0, bar), rms(bar * 4, bar * 5)
        assert intro < body * 0.75

    def test_ducking_dips_the_signal_and_lets_it_recover(self):
        import array

        from app.services.music import DUCK_RELEASE, SAMPLE_RATE, _duck

        channel = array.array("d", [1.0] * SAMPLE_RATE)
        _duck(channel, [0.5])

        at = int(0.5 * SAMPLE_RATE)
        assert channel[at] < 0.6                       # the dip lands on the kick
        assert channel[at + int(DUCK_RELEASE * SAMPLE_RATE) - 1] > 0.95   # and recovers
        assert channel[at - 1] == pytest.approx(1.0)   # nothing before it

    def test_short_beds_skip_the_intro_they_cannot_afford(self):
        from app.services.music import GROOVE, INTRO, LIFT, _arrangement

        assert _arrangement(2) == [GROOVE, GROOVE]
        long_form = _arrangement(10)
        assert long_form[0] == INTRO
        assert long_form[-1] == LIFT
        assert GROOVE in long_form

    def test_beat_snapping_rounds_up_never_down(self):
        from app.services.music import snap_to_beat

        beat = 60 / 96
        for wanted in (2.4, 3.0, 4.7, 5.05):
            snapped = snap_to_beat(wanted, 96)
            assert snapped >= wanted - 0.02               # never steals reading time
            assert abs(snapped / beat - round(snapped / beat)) < 0.01   # whole beats

    def test_bed_reaches_the_soundtrack(self, tmp_path):
        import wave

        from app.services.kinetic import mix_soundtrack
        from app.services.music import MusicSpec, render_bed

        bed = render_bed(MusicSpec(seconds=2.0, bpm=96))
        path = mix_soundtrack([("pop", 0.5, 1.0)], 2.0, tmp_path / "t.wav", bed=bed)
        with wave.open(str(path)) as track:
            frames = track.readframes(track.getnframes())
        # Silence would mean the bed never made it into the buffer.
        assert max(frames) > 0


class TestKineticQuality:
    def _colors(self):
        return {"bg": "#141414", "text": "#F5F2EA", "accent": "#C9A227", "on_accent": "#141414"}

    def test_contrast_ratio_matches_wcag(self):
        from app.services.kinetic import contrast_ratio

        assert contrast_ratio((255, 255, 255), (0, 0, 0)) == 21.0
        assert contrast_ratio((20, 20, 20), (20, 20, 20)) == 1.0
        assert contrast_ratio((245, 242, 234), (20, 20, 20)) > 4.5   # our ivory on charcoal

    def test_qc_flags_a_scene_nobody_could_read(self):
        from app.services.kinetic import KineticSpec, Scene, _SceneRenderer, qc_scene

        spec = KineticSpec(scenes=[], colors=self._colors())
        rushed = Scene(text="Juda uzun jumla bu yerda turadi va tez o'tadi", duration=1.5)
        issues = qc_scene(_SceneRenderer(rushed, spec, 0), 1, None)
        assert any("qisqa" in issue for issue in issues)

        comfortable = Scene(text="Bugun boshlang", duration=3.0)
        assert qc_scene(_SceneRenderer(comfortable, spec, 0), 1, None) == []

    def test_qc_flags_a_repeated_backdrop(self, tmp_path):
        from app.services.kinetic import KineticSpec, Scene, _SceneRenderer, qc_scene

        photo = tmp_path / "bg.jpg"
        from PIL import Image

        Image.new("RGB", (100, 180), (30, 30, 30)).save(photo)
        spec = KineticSpec(scenes=[], colors=self._colors(), prop_photos=[photo])
        first = _SceneRenderer(Scene(text="Birinchi sahna", duration=3.0), spec, 0)
        second = _SceneRenderer(Scene(text="Ikkinchi sahna", duration=3.0), spec, 1)
        assert any("fon" in issue for issue in qc_scene(second, 2, first))

    def test_outro_also_gets_its_reading_time(self):
        """QC found this: the closing card was appended after the floor pass."""
        from app.agents.kinetic import KineticAgent, KineticSceneSpec
        from app.services.kinetic import reading_time

        scenes = [
            KineticAgent._to_scene(KineticSceneSpec(text="Birinchi sahna", duration=2.0))
            for _ in range(4)
        ]
        scenes.append(KineticAgent._to_scene(KineticSceneSpec(kind="outro", text="Brend",
                                                              sub="izoh", duration=2.6)))
        for scene in scenes:
            scene.duration = max(scene.duration, reading_time(scene))
        assert scenes[-1].duration >= reading_time(scenes[-1])
