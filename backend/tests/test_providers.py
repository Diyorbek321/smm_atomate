"""Provider clients tested against a mocked HTTP transport (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.exceptions import ConfigurationError, ProviderError, PublishError, TokenLimitError


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock")


@pytest.fixture
def patch_http(monkeypatch):
    """Route every provider call through a caller-supplied handler."""

    #: Modules that imported `get_client` into their own namespace.
    consumers = (
        "app.services.http",
        "app.services.telegram_publisher",
        "app.services.instagram_publisher",
        "app.services.image_gen",
        "app.services.storage",
    )

    def _install(handler):
        client = mock_client(handler)

        async def fake_get_client(name: str = "default", *, timeout=None):
            return client

        for module in consumers:
            monkeypatch.setattr(f"{module}.get_client", fake_get_client, raising=False)
        return client

    return _install


def gemini_response(text: str, finish: str = "STOP", tokens: tuple[int, int] = (10, 20)) -> dict:
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": tokens[0], "candidatesTokenCount": tokens[1]},
    }


class TestGeminiClient:
    async def test_structured_output_is_validated(self, patch_http, monkeypatch):
        from app.schemas.content import EditorOutput
        from app.services.gemini import GeminiClient

        payload = {"approved": True, "score": 8.5, "issues": [], "summary": "yaxshi"}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["generationConfig"]["responseMimeType"] == "application/json"
            assert "responseSchema" in body["generationConfig"]
            return httpx.Response(200, json=gemini_response(json.dumps(payload)))

        patch_http(handler)
        parsed, result = await GeminiClient(api_key="k").generate_structured("prompt", EditorOutput)

        assert parsed.score == 8.5
        assert result.total_tokens == 30
        assert result.cost_usd > 0

    async def test_document_is_attached_inline(self, patch_http):
        import base64

        from app.schemas.content import EditorOutput
        from app.services.gemini import GeminiClient

        pdf = b"%PDF-1.4 minimal"
        payload = {"approved": True, "score": 9.0, "issues": [], "summary": "ok"}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            parts = body["contents"][0]["parts"]
            assert parts[0]["text"] == "prompt"
            assert parts[1]["inlineData"]["mimeType"] == "application/pdf"
            assert base64.b64decode(parts[1]["inlineData"]["data"]) == pdf
            assert body["generationConfig"]["responseMimeType"] == "application/json"
            return httpx.Response(200, json=gemini_response(json.dumps(payload)))

        patch_http(handler)
        parsed, _ = await GeminiClient(api_key="k").generate_structured_document(
            "prompt", EditorOutput, data=pdf, mime_type="application/pdf"
        )
        assert parsed.score == 9.0

    async def test_non_gemini_provider_refuses_documents(self):
        from app.core.exceptions import ConfigurationError
        from app.services.openai_compat import OpenAICompatibleClient

        with pytest.raises(ConfigurationError):
            await OpenAICompatibleClient(provider="groq").generate_structured_document(
                "p", dict, data=b"%PDF-", mime_type="application/pdf"  # type: ignore[arg-type]
            )

    def test_document_llm_falls_back_to_gemini(self, monkeypatch):
        """A Groq-first deployment still reads PDFs when a Gemini key exists."""
        from app.core.config import settings
        from app.services import llm as llm_module

        monkeypatch.setattr(settings, "llm_provider", "groq", raising=False)
        monkeypatch.setattr(settings, "gemini_api_key", "k", raising=False)
        llm_module.reset_llm()
        try:
            # The chain answers for documents whether Gemini is primary or a fallback.
            assert llm_module.get_document_llm().supports_documents is True
        finally:
            llm_module.reset_llm()

    def test_document_llm_refuses_without_any_capable_provider(self, monkeypatch):
        from app.core.config import settings
        from app.core.exceptions import ConfigurationError
        from app.services import llm as llm_module

        monkeypatch.setattr(settings, "llm_provider", "groq", raising=False)
        monkeypatch.setattr(settings, "gemini_api_key", "", raising=False)
        llm_module.reset_llm()
        try:
            with pytest.raises(ConfigurationError):
                llm_module.get_document_llm()
        finally:
            llm_module.reset_llm()

    async def test_json_wrapped_in_prose_is_recovered(self, patch_http):
        from app.schemas.content import EditorOutput
        from app.services.gemini import GeminiClient

        text = 'Mana natija:\n```json\n{"approved": false, "score": 4, "issues": [], "summary": "x"}\n```'
        patch_http(lambda request: httpx.Response(200, json=gemini_response(text)))

        parsed, _ = await GeminiClient(api_key="k").generate_structured("p", EditorOutput)
        assert parsed.approved is False

    async def test_max_tokens_triggers_one_retry_then_succeeds(self, patch_http):
        from app.schemas.content import EditorOutput
        from app.services.gemini import GeminiClient

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(200, json=gemini_response('{"approved": tru', finish="MAX_TOKENS"))
            return httpx.Response(
                200, json=gemini_response('{"approved": true, "score": 7, "issues": [], "summary": "ok"}')
            )

        patch_http(handler)
        parsed, _ = await GeminiClient(api_key="k").generate_structured("p", EditorOutput)
        assert calls["n"] == 2
        assert parsed.score == 7

    async def test_persistent_token_limit_raises(self, patch_http):
        from app.schemas.content import EditorOutput
        from app.services.gemini import GeminiClient

        patch_http(lambda r: httpx.Response(200, json=gemini_response("{trunc", finish="MAX_TOKENS")))
        with pytest.raises(TokenLimitError):
            await GeminiClient(api_key="k").generate_structured("p", EditorOutput)

    async def test_safety_block_is_not_retryable(self, patch_http):
        from app.services.gemini import GeminiClient

        patch_http(lambda r: httpx.Response(200, json=gemini_response("x", finish="SAFETY")))
        with pytest.raises(ProviderError) as excinfo:
            await GeminiClient(api_key="k").generate_text("p")
        assert excinfo.value.retryable is False

    async def test_empty_candidates_reports_block_reason(self, patch_http):
        from app.services.gemini import GeminiClient

        patch_http(lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "OTHER"}}))
        with pytest.raises(ProviderError) as excinfo:
            await GeminiClient(api_key="k").generate_text("p")
        assert "OTHER" in str(excinfo.value)

    async def test_missing_api_key(self):
        from app.services.gemini import GeminiClient

        with pytest.raises(ConfigurationError):
            await GeminiClient(api_key="").generate_text("p")

    async def test_transcribe_sends_inline_audio(self, patch_http):
        from app.services.gemini import GeminiClient

        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return httpx.Response(200, json=gemini_response("Salom dunyo"))

        patch_http(handler)
        text = await GeminiClient(api_key="k").transcribe_audio(b"\x00\x01", mime_type="audio/ogg")

        assert text == "Salom dunyo"
        assert seen["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "audio/ogg"


class TestHttpRetry:
    async def test_500_is_retried_then_succeeds(self, patch_http):
        from app.services.http import request_with_retry

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(500 if calls["n"] == 1 else 200, json={"ok": True})

        patch_http(handler)
        response = await request_with_retry("test", "GET", "http://mock/x", attempts=3)
        assert response.json()["ok"] is True
        assert calls["n"] == 2

    async def test_400_is_not_retried(self, patch_http):
        from app.services.http import request_with_retry

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(400, json={"error": {"message": "bad input"}})

        patch_http(handler)
        with pytest.raises(ProviderError) as excinfo:
            await request_with_retry("test", "GET", "http://mock/x", attempts=3)
        assert calls["n"] == 1
        assert "bad input" in str(excinfo.value)

    async def test_429_raises_rate_limit(self, patch_http):
        from app.core.exceptions import RateLimitError
        from app.services.http import request_with_retry

        patch_http(lambda r: httpx.Response(429, json={"error": {"message": "slow down"}}))
        with pytest.raises(RateLimitError):
            await request_with_retry("test", "GET", "http://mock/x", attempts=2)


class TestTelegramPublisher:
    async def test_send_photo_payload(self, patch_http):
        from app.services.telegram_publisher import TelegramPublisher

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})

        patch_http(handler)
        result = await TelegramPublisher("123:ABC").send_photo("@chan", "http://img", "matn")

        assert result.message_id == "77"
        assert captured["url"].endswith("/bot123:ABC/sendPhoto")
        assert captured["body"]["parse_mode"] == "HTML"

    async def test_long_caption_is_split(self, patch_http):
        from app.services.telegram_publisher import TelegramPublisher

        methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            methods.append(str(request.url).rsplit("/", 1)[-1])
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        patch_http(handler)
        await TelegramPublisher("t").send_photo("@c", "http://i", "x" * 1500)
        assert methods == ["sendPhoto", "sendMessage"]

    async def test_quiz_serialises_options(self, patch_http):
        from app.services.telegram_publisher import TelegramPublisher

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 5}})

        patch_http(handler)
        await TelegramPublisher("t").send_quiz("@c", "Savol?", ["a", "b", "c"], correct_option_id=2)

        assert json.loads(captured["options"]) == ["a", "b", "c"]
        assert captured["type"] == "quiz"
        assert captured["correct_option_id"] == 2

    async def test_quiz_with_one_option_is_rejected(self, patch_http):
        from app.services.telegram_publisher import TelegramPublisher

        patch_http(lambda r: httpx.Response(200, json={"ok": True, "result": {}}))
        with pytest.raises(PublishError):
            await TelegramPublisher("t").send_quiz("@c", "Savol?", ["yagona"])

    async def test_api_error_marks_retryable_correctly(self, patch_http):
        from app.services.telegram_publisher import TelegramPublisher

        patch_http(
            lambda r: httpx.Response(
                400, json={"ok": False, "error_code": 400, "description": "chat not found"}
            )
        )
        with pytest.raises(PublishError) as excinfo:
            await TelegramPublisher("t").send_message("@c", "hi")
        assert excinfo.value.retryable is False

    async def test_429_is_retryable(self, patch_http):
        from app.services.telegram_publisher import TelegramPublisher

        patch_http(
            lambda r: httpx.Response(
                429,
                json={"ok": False, "error_code": 429, "description": "Too Many Requests",
                      "parameters": {"retry_after": 5}},
            )
        )
        with pytest.raises(PublishError) as excinfo:
            await TelegramPublisher("t").send_message("@c", "hi")
        assert excinfo.value.retryable is True

    async def test_album_falls_back_to_photo_for_single_image(self, patch_http):
        from app.services.telegram_publisher import TelegramPublisher

        methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            methods.append(str(request.url).rsplit("/", 1)[-1])
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        patch_http(handler)
        await TelegramPublisher("t").send_album("@c", ["http://one"], "cap")
        assert methods == ["sendPhoto"]


class TestInstagramPublisher:
    def _handler(self, calls: list[str]):
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            calls.append(f"{request.method} {path}")
            if path.endswith("/media"):
                return httpx.Response(200, json={"id": "container-1"})
            if path.endswith("/media_publish"):
                return httpx.Response(200, json={"id": "media-99"})
            if "permalink" in str(request.url):
                return httpx.Response(200, json={"permalink": "https://instagram.com/p/x"})
            return httpx.Response(200, json={"status_code": "FINISHED"})

        return handler

    async def test_single_image_flow(self, patch_http):
        from app.services.instagram_publisher import InstagramPublisher

        calls: list[str] = []
        patch_http(self._handler(calls))

        result = await InstagramPublisher("token", "17841400000000000").publish_image("http://i", "caption")

        assert result.media_id == "media-99"
        assert result.permalink
        assert any("media_publish" in call for call in calls)

    async def test_carousel_creates_children(self, patch_http):
        from app.services.instagram_publisher import InstagramPublisher

        calls: list[str] = []
        patch_http(self._handler(calls))

        await InstagramPublisher("token", "ig").publish_carousel(
            ["http://a", "http://b", "http://c"], "caption"
        )
        # 3 children + 1 carousel container = 4 POSTs to /media
        assert sum(1 for call in calls if call.endswith("/media")) == 4

    async def test_carousel_requires_two_images(self, patch_http):
        from app.services.instagram_publisher import InstagramPublisher

        patch_http(self._handler([]))
        with pytest.raises(PublishError):
            await InstagramPublisher("token", "ig").publish_carousel(["http://only"], "c")

    async def test_expired_token_is_not_retryable(self, patch_http):
        from app.services.instagram_publisher import InstagramPublisher

        patch_http(
            lambda r: httpx.Response(
                400, json={"error": {"message": "Session expired", "code": 190, "error_subcode": 463}}
            )
        )
        with pytest.raises(PublishError) as excinfo:
            await InstagramPublisher("token", "ig").publish_image("http://i", "c")
        assert excinfo.value.retryable is False
        assert excinfo.value.details["token_expired"] is True

    async def test_container_error_aborts(self, patch_http):
        from app.services.instagram_publisher import InstagramPublisher

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/media"):
                return httpx.Response(200, json={"id": "c1"})
            return httpx.Response(200, json={"status_code": "ERROR", "status": "bad media"})

        patch_http(handler)
        with pytest.raises(PublishError) as excinfo:
            await InstagramPublisher("token", "ig").publish_image("http://i", "c")
        assert "ERROR" in str(excinfo.value)

    async def test_missing_credentials(self):
        from app.services.instagram_publisher import InstagramPublisher

        with pytest.raises(ConfigurationError):
            InstagramPublisher(None, "ig")


class TestImageGenerator:
    async def test_fal_returns_stored_url(self, patch_http, monkeypatch, tmp_path):
        from app.services.image_gen import ImageGenerator

        monkeypatch.setattr("app.core.config.settings.fal_api_key", "fal-key", raising=False)
        monkeypatch.setattr("app.core.config.settings.media_root", tmp_path, raising=False)
        monkeypatch.setattr("app.services.storage._storage", None, raising=False)

        png = b"\x89PNG\r\n\x1a\n" + b"0" * 32

        def handler(request: httpx.Request) -> httpx.Response:
            if "fal.run" in str(request.url):
                assert request.headers["authorization"] == "Key fal-key"
                return httpx.Response(200, json={"images": [{"url": "http://cdn/img.png"}]})
            return httpx.Response(200, content=png, headers={"content-type": "image/png"})

        patch_http(handler)
        image = await ImageGenerator("fal").generate("a cat", aspect_ratio="4:5")

        assert image.provider == "fal"
        assert image.stored is not None
        assert image.stored.path.read_bytes() == png

    async def test_fal_without_images_raises(self, patch_http, monkeypatch):
        from app.services.image_gen import ImageGenerator

        monkeypatch.setattr("app.core.config.settings.fal_api_key", "fal-key", raising=False)
        patch_http(lambda r: httpx.Response(200, json={"images": []}))

        with pytest.raises(ProviderError):
            await ImageGenerator("fal").generate("a cat")

    async def test_disabled_provider_raises(self, monkeypatch):
        from app.services.image_gen import ImageGenerator

        monkeypatch.setattr("app.core.config.settings.fal_api_key", "", raising=False)
        generator = ImageGenerator("fal")
        assert generator.enabled is False
        with pytest.raises(ConfigurationError):
            await generator.generate("x")


class TestTranscription:
    async def test_whisper_path(self, patch_http, monkeypatch):
        from app.services.transcription import TranscriptionService

        monkeypatch.setattr("app.core.config.settings.openai_api_key", "sk-test", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            assert "audio/transcriptions" in str(request.url)
            return httpx.Response(200, json={"text": "Narxni 400 ming qil"})

        patch_http(handler)
        text = await TranscriptionService("openai").transcribe(b"audio-bytes")
        assert text == "Narxni 400 ming qil"

    async def test_falls_back_to_gemini_when_whisper_fails(self, patch_http, monkeypatch):
        from app.services.transcription import TranscriptionService

        monkeypatch.setattr("app.core.config.settings.openai_api_key", "sk-test", raising=False)
        monkeypatch.setattr("app.core.config.settings.gemini_api_key", "gem-key", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            if "openai.com" in str(request.url):
                return httpx.Response(400, json={"error": {"message": "bad audio"}})
            return httpx.Response(200, json=gemini_response("Gemini transkripsiyasi"))

        patch_http(handler)
        text = await TranscriptionService("openai").transcribe(b"audio")
        assert text == "Gemini transkripsiyasi"

    async def test_no_provider_configured(self, monkeypatch):
        from app.services.transcription import TranscriptionService

        monkeypatch.setattr("app.core.config.settings.openai_api_key", "", raising=False)
        monkeypatch.setattr("app.core.config.settings.gemini_api_key", "", raising=False)
        with pytest.raises(ConfigurationError):
            await TranscriptionService("openai").transcribe(b"audio")


class TestSchemaModeDowngrade:
    """Strict JSON mode must degrade only for the right reasons."""

    def _error(self, message: str):
        from app.core.exceptions import ProviderError

        return ProviderError("groq", message, retryable=False)

    def test_schema_complaints_downgrade(self):
        from app.services.openai_compat import _schema_mode_rejected

        for message in (
            "Failed to generate JSON. Please adjust your prompt.",
            "Generated JSON does not match the expected schema.",
            "response_format json_schema is not supported for this model",
        ):
            assert _schema_mode_rejected(self._error(message)), message

    def test_rate_limit_does_not_downgrade(self):
        from app.core.exceptions import RateLimitError
        from app.services.openai_compat import _schema_mode_rejected

        error = RateLimitError("groq", "Rate limit reached for model, try again in 45s")
        assert _schema_mode_rejected(error) is False

    def test_token_limit_does_not_downgrade(self):
        from app.core.exceptions import TokenLimitError
        from app.services.openai_compat import _schema_mode_rejected

        assert _schema_mode_rejected(TokenLimitError("groq", "output truncated")) is False

    def test_auth_failure_does_not_downgrade(self):
        from app.services.openai_compat import _schema_mode_rejected

        assert _schema_mode_rejected(self._error("Invalid API key provided")) is False


class TestOpenAICompatibleClient:
    async def test_structured_output_via_json_schema(self, patch_http):
        from app.schemas.content import EditorOutput
        from app.services.openai_compat import OpenAICompatibleClient

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"approved": true, "score": 9, "issues": [], "summary": "ok"}'
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                },
            )

        patch_http(handler)
        client = OpenAICompatibleClient(provider="groq", api_key="k", base_url="http://mock/v1")
        parsed, result = await client.generate_structured("prompt", EditorOutput, system="sys")

        assert parsed.score == 9
        assert result.provider == "groq"
        assert result.total_tokens == 150
        assert captured["response_format"]["type"] == "json_schema"
        # Strict mode requires every property to be required.
        schema = captured["response_format"]["json_schema"]["schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])

    async def test_falls_back_to_json_object_when_schema_is_refused(self, patch_http):
        from app.schemas.content import EditorOutput
        from app.services.openai_compat import _SCHEMA_MODE, OpenAICompatibleClient

        _SCHEMA_MODE.clear()
        modes: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            modes.append(body["response_format"]["type"])
            if body["response_format"]["type"] == "json_schema":
                return httpx.Response(
                    400, json={"error": {"message": "Failed to generate JSON. Adjust your prompt."}}
                )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": '{"approved": false, "score": 4, "issues": [], "summary": "x"}'},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )

        patch_http(handler)
        client = OpenAICompatibleClient(provider="groq", api_key="k", base_url="http://mock/v1")
        parsed, _ = await client.generate_structured("p", EditorOutput)

        assert parsed.score == 4
        assert modes == ["json_schema", "json_object"]
        # The downgrade is remembered so the next call skips the failed attempt.
        assert _SCHEMA_MODE["groq:openai/gpt-oss-20b"] is False
        _SCHEMA_MODE.clear()

    async def test_truncated_output_raises_token_limit(self, patch_http):
        from app.services.openai_compat import OpenAICompatibleClient

        patch_http(
            lambda r: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "{trunc"}, "finish_reason": "length"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 4000},
                },
            )
        )
        client = OpenAICompatibleClient(provider="groq", api_key="k", base_url="http://mock/v1")
        with pytest.raises(TokenLimitError):
            await client.generate_text("p")

    async def test_missing_key_is_a_configuration_error(self, monkeypatch):
        from app.services.openai_compat import OpenAICompatibleClient

        monkeypatch.setattr("app.core.config.settings.groq_api_key", "", raising=False)
        with pytest.raises(ConfigurationError):
            await OpenAICompatibleClient(provider="groq").generate_text("p")

    async def test_whisper_goes_to_the_provider_endpoint(self, patch_http):
        from app.services.openai_compat import OpenAICompatibleClient

        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"text": "Narxni 400 ming qil"})

        patch_http(handler)
        client = OpenAICompatibleClient(provider="groq", api_key="k", base_url="http://mock/v1")
        text = await client.transcribe_audio(b"audio")

        assert text == "Narxni 400 ming qil"
        assert seen["url"].endswith("/audio/transcriptions")


class TestRateLimitBackoff:
    """A provider that says "wait 45s" must not be hammered 1.5s later."""

    def _state(self, error: Exception):
        from tenacity import RetryCallState

        state = RetryCallState(retry_object=None, fn=None, args=(), kwargs={})
        state.set_exception((type(error), error, None))
        return state

    def test_explicit_retry_after_is_used(self):
        from app.core.exceptions import RateLimitError
        from app.services.http import _wait_policy

        error = RateLimitError("groq", "rate limited")
        error.retry_after = 12.5
        assert _wait_policy(self._state(error)) == pytest.approx(12.5)

    def test_without_retry_after_it_backs_off_exponentially(self):
        from app.core.exceptions import ProviderError
        from app.services.http import _wait_policy

        wait = _wait_policy(self._state(ProviderError("groq", "boom")))
        assert 0 < wait <= 20

    def test_delay_is_capped(self):
        import httpx

        from app.services.http import MAX_RETRY_AFTER_SECONDS, _retry_after_seconds

        response = httpx.Response(429, headers={"retry-after": "9999"})
        assert _retry_after_seconds(response, {}) == MAX_RETRY_AFTER_SECONDS

    def test_delay_is_parsed_from_the_message(self):
        import httpx

        from app.services.http import _retry_after_seconds

        body = {"error": {"message": "Rate limit reached. Please try again in 45.4s."}}
        assert _retry_after_seconds(httpx.Response(429), body) == pytest.approx(45.4)

    async def test_rate_limited_call_is_retried_then_succeeds(self, patch_http):
        from app.services.http import request_with_retry

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(
                    429,
                    headers={"retry-after": "0"},
                    json={"error": {"message": "Rate limit reached"}},
                )
            return httpx.Response(200, json={"ok": True})

        patch_http(handler)
        response = await request_with_retry("groq", "GET", "http://mock/x", attempts=3)
        assert response.json()["ok"] is True
        assert calls["n"] == 2


class TestVideoGenerator:
    async def test_fal_animation_is_downloaded_and_stored(self, patch_http, monkeypatch, tmp_path):
        from app.core.config import settings
        from app.services.storage import MediaStorage
        from app.services.video_gen import VideoGenerator

        monkeypatch.setattr(settings, "fal_api_key", "k", raising=False)
        storage = MediaStorage(tmp_path)
        monkeypatch.setattr("app.services.video_gen.get_storage", lambda: storage)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                body = json.loads(request.content)
                assert body["image_url"].startswith("data:image/")
                assert body["prompt"]
                return httpx.Response(200, json={"video": {"url": "http://mock/clip.mp4"}})
            return httpx.Response(200, content=b"ftyp-fake-mp4-bytes",
                                  headers={"content-type": "video/mp4"})

        patch_http(handler)
        stored = await VideoGenerator().animate("data:image/jpeg;base64,QUJD", "motion")
        assert stored.filename.endswith(".mp4")
        assert stored.path.read_bytes() == b"ftyp-fake-mp4-bytes"

    async def test_disabled_without_key(self, monkeypatch):
        from app.core.config import settings
        from app.core.exceptions import ConfigurationError
        from app.services.video_gen import VideoGenerator

        monkeypatch.setattr(settings, "fal_api_key", "", raising=False)
        with pytest.raises(ConfigurationError):
            await VideoGenerator().animate("data:image/jpeg;base64,QUJD")


class TestProviderFallback:
    """A daily quota on one vendor must not take the whole service down."""

    def _fake(self, name: str, *, fails: bool = False, documents: bool = False):
        from typing import ClassVar

        from app.core.exceptions import ProviderError
        from app.services.llm import LLMClient, LLMResult

        class Fake(LLMClient):
            provider = name
            supports_documents = documents
            calls: ClassVar[list[dict]] = []

            @property
            def model_fast(self) -> str:
                return f"{name}-fast"

            @property
            def model_pro(self) -> str:
                return f"{name}-pro"

            async def generate_text(self, prompt, *, model=None, **kwargs):
                Fake.calls.append({"provider": name, "model": model})
                if fails:
                    raise ProviderError(name, "quota", retryable=False)
                return LLMResult(text=f"{name} javobi", model=self.model_fast)

            async def generate_structured(self, prompt, schema, *, model=None, **kwargs):
                Fake.calls.append({"provider": name, "model": model})
                if fails:
                    raise ProviderError(name, "quota", retryable=False)
                return schema(), LLMResult(text="{}", model=self.model_fast)

            async def generate_structured_document(self, prompt, schema, **kwargs):
                Fake.calls.append({"provider": name, "model": "doc"})
                return schema(), LLMResult(text="{}", model=self.model_fast)

            async def transcribe_audio(self, audio, mime_type="audio/ogg", language="uz"):
                if fails:
                    raise ProviderError(name, "quota", retryable=False)
                return f"{name} matn"

        return Fake()

    async def test_second_provider_answers_when_the_first_is_out_of_quota(self):
        from app.services.llm import FallbackLLM

        primary, backup = self._fake("groq", fails=True), self._fake("gemini")
        result = await FallbackLLM([primary, backup]).generate_text("salom", model="groq-fast")
        assert result.text == "gemini javobi"

    async def test_only_the_primary_is_given_a_model_name(self):
        """Model ids are provider-specific — passing one along would break the fallback."""
        from app.services.llm import FallbackLLM

        primary, backup = self._fake("groq", fails=True), self._fake("gemini")
        type(primary).calls = []
        type(backup).calls = []
        await FallbackLLM([primary, backup]).generate_text("salom", model="openai/gpt-oss-20b")
        assert type(primary).calls[0]["model"] == "openai/gpt-oss-20b"
        assert type(backup).calls[0]["model"] is None

    async def test_documents_route_to_a_provider_that_can_read_them(self):
        from app.schemas.content import EditorOutput
        from app.services.llm import FallbackLLM

        plain, multimodal = self._fake("groq"), self._fake("gemini", documents=True)
        chain = FallbackLLM([plain, multimodal])
        assert chain.supports_documents is True
        parsed, _ = await chain.generate_structured_document(
            "p", EditorOutput, data=b"%PDF-", mime_type="application/pdf"
        )
        assert parsed is not None

    async def test_every_provider_failing_raises(self):
        from app.core.exceptions import ProviderError
        from app.services.llm import FallbackLLM

        chain = FallbackLLM([self._fake("groq", fails=True), self._fake("gemini", fails=True)])
        with pytest.raises(ProviderError):
            await chain.generate_text("salom")

    def test_chain_skips_providers_without_a_key(self, monkeypatch):
        from app.core.config import settings
        from app.services.llm import provider_chain

        monkeypatch.setattr(settings, "llm_provider", "gemini", raising=False)
        monkeypatch.setattr(settings, "llm_fallbacks", "groq,openai", raising=False)
        monkeypatch.setattr(settings, "groq_api_key", "k", raising=False)
        monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
        assert provider_chain() == ["gemini", "groq"]

        monkeypatch.setattr(settings, "llm_fallbacks", "gemini", raising=False)
        assert provider_chain() == ["gemini"]           # no duplicate of the primary


class TestLocalMediaUpload:
    """Telegram cannot fetch `localhost` URLs — our own files go up as bytes."""

    @pytest.fixture
    def media(self, monkeypatch, tmp_path):
        from app.core.config import settings

        monkeypatch.setattr(settings, "media_root", tmp_path, raising=False)
        monkeypatch.setattr(settings, "public_base_url", "http://localhost:8000", raising=False)

        def _write(name: str, data: bytes = b"PNGDATA") -> str:
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return f"http://localhost:8000/media/{name}"

        return _write

    def test_resolves_our_own_url(self, media):
        from app.services.storage import local_media_path

        url = media("20260821/card.png")
        assert local_media_path(url).read_bytes() == b"PNGDATA"

    def test_ignores_foreign_and_missing(self, media):
        from app.services.storage import local_media_path

        media("x.png")
        assert local_media_path("https://cdn.example.com/a.png") is None
        assert local_media_path("http://localhost:8000/media/gone.png") is None
        assert local_media_path(None) is None

    def test_rejects_path_traversal(self, media, tmp_path):
        from app.services.storage import local_media_path

        (tmp_path.parent / "secret.env").write_bytes(b"TOKEN")
        assert local_media_path("http://localhost:8000/media/../secret.env") is None

    async def test_send_photo_uploads_local_file(self, patch_http, media):
        from app.services.telegram_publisher import TelegramPublisher

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["type"] = request.headers.get("content-type", "")
            captured["body"] = request.content
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

        patch_http(handler)
        url = media("20260821/card.png")
        result = await TelegramPublisher("t").send_photo("@chan", url, "matn")

        assert result.message_id == "9"
        assert captured["type"].startswith("multipart/form-data")
        assert b'name="photo"; filename="card.png"' in captured["body"]
        assert b"PNGDATA" in captured["body"]
        assert b"localhost:8000" not in captured["body"]      # the URL never leaves

    async def test_album_attaches_local_slides(self, patch_http, media):
        from app.services.telegram_publisher import TelegramPublisher

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content
            return httpx.Response(200, json={"ok": True, "result": [{"message_id": 3}]})

        patch_http(handler)
        slides = [media("20260821/s1.png"), media("20260821/s2.png"), "https://cdn.example.com/s3.png"]
        await TelegramPublisher("t").send_album("@chan", slides, "cap")

        body = captured["body"]
        assert b"attach://file0" in body and b"attach://file1" in body
        assert b'filename="s1.png"' in body and b'filename="s2.png"' in body
        assert b"https://cdn.example.com/s3.png" in body       # foreign URLs still pass through

    async def test_remote_url_still_sent_as_json(self, patch_http, media):
        from app.services.telegram_publisher import TelegramPublisher

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["type"] = request.headers.get("content-type", "")
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        patch_http(handler)
        await TelegramPublisher("t").send_photo("@c", "https://cdn.example.com/a.png", "x")
        assert captured["type"].startswith("application/json")
        assert captured["body"]["photo"] == "https://cdn.example.com/a.png"


class TestUploadTimeout:
    """A pooled client keeps its original timeout — uploads must override it."""

    def test_scales_with_payload_and_stays_bounded(self, tmp_path):
        from app.services.telegram_publisher import (
            UPLOAD_TIMEOUT_CEILING,
            UPLOAD_TIMEOUT_FLOOR,
            _upload_timeout,
        )

        small = tmp_path / "small.png"
        small.write_bytes(b"x" * 1024)
        assert _upload_timeout({"photo": small}).read == UPLOAD_TIMEOUT_FLOOR

        medium = tmp_path / "medium.mp4"
        medium.write_bytes(b"x" * 20_000_000)
        assert UPLOAD_TIMEOUT_FLOOR < _upload_timeout({"video": medium}).read < UPLOAD_TIMEOUT_CEILING

        huge = tmp_path / "huge.mp4"
        huge.write_bytes(b"x" * 50_000_000)
        assert _upload_timeout({"video": huge}).read == UPLOAD_TIMEOUT_CEILING
        assert _upload_timeout({"video": huge}).connect == 15.0

    async def test_request_carries_the_override(self, patch_http, monkeypatch, tmp_path):
        from app.core.config import settings
        from app.services.telegram_publisher import TelegramPublisher

        monkeypatch.setattr(settings, "media_root", tmp_path, raising=False)
        monkeypatch.setattr(settings, "public_base_url", "http://localhost:8000", raising=False)
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 5_000_000)

        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["timeout"] = request.extensions.get("timeout", {})
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        patch_http(handler)
        await TelegramPublisher("t").send_video("@c", "http://localhost:8000/media/clip.mp4", "x")

        assert seen["timeout"]["read"] > 60          # not the pooled default
        assert seen["timeout"]["connect"] == 15.0
