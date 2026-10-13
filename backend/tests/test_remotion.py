"""The Remotion engine: timing, sound cues, grounding, the render client, the API.

The render service itself is Node (``backend/remotion``) and has its own tests;
these pin the Python half of the contract — including one test that feeds a
Python-built script to the Node validator, so the two sides cannot drift apart.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from app.core.exceptions import ConfigurationError, ProviderError
from app.services.promo_families import Brand
from app.services.remotion_script import (
    FeatureCopy,
    PromoCopy,
    build_script,
    pattern_for,
)

REMOTION_DIR = Path(__file__).resolve().parents[1] / "remotion"


def make_copy(**overrides) -> PromoCopy:
    base = dict(
        hook=["Ishga?", "Uchrashuvga?"], lead="Qayerga bo'lmasin —", punch="Kechikmang.",
        tagline="Shahringiz taksisi",
        features=[FeatureCopy("Tezkor", "Tez yetib kelamiz", "Tez", "Mashina yo'lda.", "bolt"),
                  FeatureCopy("Qulay", "Qulay narx", "narx", "Yashirin to'lovsiz.", "wallet")],
        list_title="Nega aynan biz?", list_accent="biz?", items=["Toza salon", "Tajriba", "Xushmuomala"],
        stat_value=12000, stat_suffix="+", stat_label="mamnun yo'lovchi",
        cta_tagline="Yo'lingiz ishonchli qo'llarda", cta_accent="ishonchli", button="Buyurtma bering",
    )
    return PromoCopy(**{**base, **overrides})


def script(**overrides) -> dict:
    return build_script(make_copy(**overrides), Brand.from_colors({}, mark="Angren Taxi"),
                        name="ANGREN TAXI", contact="+998901234567")


class TestTiming:
    def test_every_cut_lands_on_a_bar_line(self):
        s = script()
        bar = s["props"]["beat"] * 4
        for scene in s["props"]["scenes"]:
            assert scene["at"][0] / bar == pytest.approx(round(scene["at"][0] / bar), abs=1e-3)

    def test_scenes_are_contiguous_and_fill_the_duration(self):
        scenes = script()["props"]["scenes"]
        for prev, nxt in zip(scenes, scenes[1:], strict=False):
            assert prev["at"][1] == nxt["at"][0]
        assert scenes[0]["at"][0] == 0
        assert scenes[-1]["at"][1] == script()["duration"] == script()["props"]["duration"]

    def test_order_is_hook_logo_features_list_stat_cta(self):
        kinds = [s["type"] for s in script()["props"]["scenes"]]
        assert kinds == ["hook", "logo", "feature", "feature", "list", "stat", "cta"]

    def test_optional_scenes_drop_out_when_empty(self):
        kinds = [s["type"] for s in script(items=[], stat_value=0)["props"]["scenes"]]
        assert "list" not in kinds and "stat" not in kinds

    def test_features_are_capped_at_three(self):
        many = [FeatureCopy("a", "b c", "b", "d")] * 5
        kinds = [s["type"] for s in script(features=many)["props"]["scenes"]]
        assert kinds.count("feature") == 3

    def test_an_accent_missing_from_its_title_is_cleared(self):
        feature = FeatureCopy("Tezkor", "Tez yetib kelamiz", "Arzon", "x")
        scene = next(s for s in script(features=[feature])["props"]["scenes"] if s["type"] == "feature")
        assert scene["accent"] == ""

    def test_an_unknown_icon_falls_back_to_star(self):
        feature = FeatureCopy("a", "b c", "b", "d", icon="rocket")
        scene = next(s for s in script(features=[feature])["props"]["scenes"] if s["type"] == "feature")
        assert scene["icon"] == "star"

    def test_the_brand_palette_reaches_the_renderer(self):
        brand = Brand.from_colors({"accent": "#FFC400", "bg": "#0B0B0C"}, mark="X")
        s = build_script(make_copy(), brand, name="X")
        assert s["props"]["palette"]["accent"] == "#FFC400"
        assert s["music"]["key_shift"] == brand.key_shift

    def test_a_tempo_without_whole_frame_bars_is_refused(self):
        with pytest.raises(ValueError):
            build_script(make_copy(), Brand.from_colors({}, mark="X"), name="X", bpm=128)

    def test_scene_edges_are_whole_frames(self):
        s = script()
        for scene in s["props"]["scenes"]:
            for edge in scene["at"]:
                assert edge * 30 == pytest.approx(round(edge * 30), abs=1e-6)

    def test_taxis_get_the_checker_band(self):
        assert pattern_for("Angren Taxi") == "checker"
        assert pattern_for("Bright Academy", "education") == "stripes"


class TestCues:
    def test_cues_stay_inside_the_clip(self):
        s = script()
        assert all(0 <= at <= s["duration"] for _, at, _ in s["cues"])

    def test_every_cut_after_the_first_gets_a_whoosh_just_before_it(self):
        s = script()
        whooshes = [at for name, at, _ in s["cues"] if name == "whoosh"]
        cuts = [scene["at"][0] for scene in s["props"]["scenes"][1:]]
        assert whooshes == pytest.approx([cut - 0.12 for cut in cuts])

    def test_only_sounds_the_mixer_knows_are_used(self):
        from app.services.kinetic import sfx_library

        known = set(sfx_library())
        assert {name for name, _, _ in script()["cues"]} <= known


class TestGrounding:
    def test_a_number_from_the_knowledge_base_is_kept(self):
        from app.agents.remotion_promo import grounded

        assert grounded(12000, "Bizda 12 000 dan ortiq mijoz bor")
        assert grounded(600000, "narx: 600000 UZS")

    def test_an_invented_number_is_dropped(self):
        from app.agents.remotion_promo import grounded

        assert not grounded(5000, "Bizda 12 000 mijoz bor")
        assert not grounded(0, "0")
        assert not grounded(120, "12000")


class TestAgent:
    def _schema(self, **overrides):
        from app.agents.remotion_promo import RemotionCopySchema

        data = dict(
            hook=["Kechikyapsizmi?", "Yo'l uzoqmi?"], lead="", punch="Biz bormiz.",
            tagline="Shahringiz taksisi",
            features=[{"label": "Tezkor", "title": "Tez yetib kelamiz", "accent": "Tez",
                       "subtitle": "Mashina yo'lda.", "icon": "bolt"}],
            list_title="", list_accent="", items=[], stat_value=999999, stat_suffix="+",
            stat_label="yo'lovchi", cta_tagline="Ishonchli yo'l", cta_accent="Ishonchli",
            button="Buyurtma bering",
        )
        return RemotionCopySchema(**{**data, **overrides})

    async def _write(self, monkeypatch, answers):
        from app.agents.remotion_promo import RemotionPromoAgent
        from tests.test_agents import make_business, make_knowledge

        agent = RemotionPromoAgent()
        prompts: list[str] = []
        queue = list(answers)

        async def fake_ask_json(prompt, schema, **kwargs):
            prompts.append(prompt)
            return queue.pop(0)

        async def fake_system_prompt(default, **kwargs):
            return default

        monkeypatch.setattr(agent, "ask_json", fake_ask_json)
        monkeypatch.setattr(agent, "system_prompt", fake_system_prompt)
        written = await agent.write(make_business(), make_knowledge(), "Tez taksi")
        return written, prompts

    async def test_an_ungrounded_stat_never_reaches_the_screen(self, monkeypatch):
        written, _ = await self._write(monkeypatch, [self._schema()])
        kinds = [s["type"] for s in written.script["props"]["scenes"]]
        assert "stat" not in kinds

    async def test_the_contact_comes_from_the_knowledge_base(self, monkeypatch):
        written, _ = await self._write(monkeypatch, [self._schema()])
        cta = written.script["props"]["scenes"][-1]
        assert cta["contact"] == "+998901234567"

    async def test_a_placeholder_is_retried_with_the_complaint(self, monkeypatch):
        written, prompts = await self._write(
            monkeypatch, [self._schema(punch="[narx]"), self._schema()])
        assert len(prompts) == 2 and "OLDINGI URINISH XATOSI" in prompts[1]
        assert written.script["props"]["scenes"][0]["punch"] == "Biz bormiz."

    async def test_an_overlong_line_is_sent_back_not_cut_mid_word(self, monkeypatch):
        long = self._schema(cta_tagline="Hozir yo'lga chiqing va sinab ko'ring albatta")
        written, prompts = await self._write(monkeypatch, [long, self._schema()])
        assert len(prompts) == 2 and "belgidan uzun" in prompts[1]
        assert written.script["props"]["scenes"][-1]["tagline"] == "Ishonchli yo'l"

    async def test_a_slightly_long_line_survives_intact(self, monkeypatch):
        """Cutting "Mashina kutyapsizmi?" to fit left just "Mashina" on screen."""
        long = self._schema(hook=["Mashina kutyapsizmi?", "Yo'l uzoqmi?"])
        written, _ = await self._write(monkeypatch, [long, long])
        assert written.script["props"]["scenes"][0]["lines"][0] == "Mashina kutyapsizmi?"

    async def test_a_far_too_long_line_is_trimmed_between_words(self, monkeypatch):
        sentence = "Hozir yo'lga chiqing va sinab ko'ring albatta bugunoq kechikmasdan do'stlar"
        long = self._schema(cta_tagline=sentence)
        written, _ = await self._write(monkeypatch, [long, long])
        tagline = written.script["props"]["scenes"][-1]["tagline"]
        assert len(tagline) <= 57 and sentence.startswith(tagline)
        assert sentence[len(tagline)] == " "                     # ended on a word boundary

    def test_clip_words_never_splits_a_word(self):
        from app.agents.remotion_promo import clip_words

        assert clip_words("Tajribali xushmuomala haydovchilar", 26) == "Tajribali xushmuomala"
        assert clip_words("qisqa", 26) == "qisqa"
        assert clip_words("Xushmuomalalikkabag'ishlangan", 10) == "Xushmuomalalikkabag'ishlangan"

    async def test_two_bad_answers_raise(self, monkeypatch):
        with pytest.raises(ProviderError):
            await self._write(monkeypatch, [self._schema(button="")] * 2)


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestRenderClient:
    @pytest.fixture(autouse=True)
    def configured(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "remotion_url", "http://remotion:3001/")

    async def test_posts_composition_and_props_and_returns_bytes(self):
        from app.services.remotion import request_render

        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, content=b"MP4", headers={"content-type": "video/mp4"})

        s = script()
        async with mock_client(handler) as client:
            data = await request_render(s, client=client)
        assert data == b"MP4"
        assert seen["url"] == "http://remotion:3001/render"
        assert set(seen["body"]) == {"composition", "props"}          # no cues/music leak out

    async def test_a_rejected_script_is_not_retryable(self):
        from app.services.remotion import request_render

        def handler(request):
            return httpx.Response(422, json={"error": "invalid request", "details": ["bad"]})

        async with mock_client(handler) as client:
            with pytest.raises(ProviderError) as info:
                await request_render(script(), client=client)
        assert info.value.retryable is False

    async def test_an_unreachable_service_is_retryable(self):
        from app.services.remotion import request_render

        def handler(request):
            raise httpx.ConnectError("refused")

        async with mock_client(handler) as client:
            with pytest.raises(ProviderError) as info:
                await request_render(script(), client=client)
        assert info.value.retryable is True

    async def test_a_non_video_answer_is_an_error(self):
        from app.services.remotion import request_render

        def handler(request):
            return httpx.Response(200, json={"ok": True})

        async with mock_client(handler) as client:
            with pytest.raises(ProviderError):
                await request_render(script(), client=client)

    async def test_missing_url_is_a_configuration_error(self, monkeypatch):
        from app.core.config import settings
        from app.services.remotion import request_render

        monkeypatch.setattr(settings, "remotion_url", "")
        with pytest.raises(ConfigurationError):
            await request_render(script())


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
class TestSoundIsLaidUnderThePicture:
    async def test_a_muted_render_comes_back_with_audio_and_a_cover(self, monkeypatch, tmp_path):
        import app.services.remotion as remotion
        import app.services.storage as storage

        s = build_script(make_copy(features=[FeatureCopy("a", "b c", "b", "d")], items=[], stat_value=0),
                         Brand.from_colors({}, mark="X"), name="X", bpm=240)
        silent = tmp_path / "silent.mp4"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
             f"color=c=black:s=108x192:r=30:d={s['duration']}", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", str(silent)],
            check=True,
        )

        async def fake_render(_script, **kwargs):
            return silent.read_bytes()

        monkeypatch.setattr(remotion, "request_render", fake_render)
        monkeypatch.setattr(storage, "_storage", storage.MediaStorage(tmp_path / "media"))
        result = await remotion.render_remotion(s)

        assert result.video.path.exists() and result.cover is not None
        probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(result.video.path)],
                               capture_output=True, text=True)
        assert "Audio:" in probe.stderr and "Video:" in probe.stderr


@pytest.mark.skipif(shutil.which("node") is None or not (REMOTION_DIR / "validate.mjs").exists(),
                    reason="node or the remotion service is not available")
class TestContractWithTheRenderer:
    def test_a_python_built_script_passes_the_node_validator(self):
        s = script()
        body = json.dumps({"composition": s["composition"], "props": s["props"]})
        code = (
            "import('./validate.mjs').then(({validateRequest}) => {"
            "let d='';process.stdin.on('data',c=>d+=c).on('end',()=>{"
            "const e=validateRequest(JSON.parse(d));console.log(JSON.stringify(e));"
            "process.exit(e.length?1:0)})})"
        )
        result = subprocess.run(["node", "-e", code], input=body, cwd=REMOTION_DIR,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.db
class TestEndpoint:
    async def _business(self, client, payload, plan):
        response = await client.post("/api/v1/businesses", json={**payload, "plan": plan})
        return response.json()["data"]["id"]

    @pytest.fixture(autouse=True)
    def configured(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "remotion_url", "http://remotion:3001")

    async def test_topic_is_required(self, client):
        response = await client.post("/api/v1/generate/remotion", json={"business_id": "x"})
        assert response.status_code == 422

    async def test_a_non_pro_business_is_refused(self, client, business_payload):
        business_id = await self._business(client, business_payload, "standard")
        response = await client.post("/api/v1/generate/remotion",
                                     json={"business_id": business_id, "topic": "Tez taksi"})
        assert response.status_code == 422
        assert "Pro" in response.text

    async def test_a_pro_business_is_queued(self, client, business_payload, monkeypatch):
        import app.api.v1.generation as generation

        queued = {}

        def fake_enqueue(task, *args, **kwargs):
            queued.update(task=task, args=args, kwargs=kwargs)
            return "task-1"

        monkeypatch.setattr(generation, "_enqueue", fake_enqueue)
        business_id = await self._business(client, business_payload, "pro")
        response = await client.post("/api/v1/generate/remotion",
                                     json={"business_id": business_id, "topic": "Tez taksi"})
        assert response.status_code == 200
        assert response.json()["data"]["task_id"] == "task-1"
        assert queued["task"] == "app.tasks.generation.render_remotion_clip"

    async def test_an_unconfigured_engine_says_so(self, client, business_payload, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "remotion_url", "")
        business_id = await self._business(client, business_payload, "pro")
        response = await client.post("/api/v1/generate/remotion",
                                     json={"business_id": business_id, "topic": "Tez taksi"})
        assert response.status_code == 400
        assert "REMOTION_URL" in response.text
