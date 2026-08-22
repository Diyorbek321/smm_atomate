"""Flux.1 Schnell image generation via fal.ai (default) or Replicate."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.exceptions import ConfigurationError, ProviderError
from app.core.logging import get_logger
from app.services.http import get_client, request_with_retry
from app.services.storage import StoredFile, get_storage

log = get_logger(__name__)

#: Aspect ratio -> pixel size understood by Flux.
SIZE_PRESETS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}

DEFAULT_NEGATIVE = (
    "text, watermark, logo, letters, typography, distorted faces, extra fingers, "
    "low quality, blurry, jpeg artifacts, oversaturated"
)

#: Per-model payload extras. The whole Flux family is guidance-distilled, so
#: none of these endpoints accept a `negative_prompt` field — passing one is
#: silently ignored, which is how the constraint above went years without
#: reaching a single render. The working substitute is to spell the ban out in
#: the prompt itself (:func:`with_constraints`), which Flux does respect.
MODEL_PARAMS: dict[str, dict[str, Any]] = {
    "fal-ai/flux/schnell": {"num_inference_steps": 4, "output_format": "png"},
    "fal-ai/flux/dev": {"num_inference_steps": 28, "guidance_scale": 3.5, "output_format": "png"},
    "fal-ai/flux-pro/v1.1": {"output_format": "png", "safety_tolerance": "2"},
}

#: An unknown model gets a full sampler rather than the fast one — a new model
#: is far more likely to be a better one than a distilled speed variant.
FALLBACK_PARAMS: dict[str, Any] = {"num_inference_steps": 28, "output_format": "png"}


def model_params(model: str) -> dict[str, Any]:
    if model in MODEL_PARAMS:
        return dict(MODEL_PARAMS[model])
    if "schnell" in model:
        return dict(MODEL_PARAMS["fal-ai/flux/schnell"])
    return dict(FALLBACK_PARAMS)


def with_constraints(prompt: str, negative: str | None) -> str:
    """Fold what must not appear into the prompt, phrased as an instruction.

    Flux has no negative conditioning, but it follows plain instructions well.
    Kept to one short sentence: a long ban list starts *summoning* the things
    it names.
    """
    banned = (negative or "").strip()
    if not banned:
        return prompt
    first = [part.strip() for part in banned.split(",") if part.strip()][:6]
    if not first:
        return prompt
    return f"{prompt.rstrip('. ')}. Absolutely no {', '.join(first)}."


@dataclass(slots=True)
class GeneratedImage:
    url: str
    provider: str
    width: int
    height: int
    prompt: str
    stored: StoredFile | None = None


class ImageGenerator:
    """Provider-agnostic text-to-image facade."""

    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider or settings.image_provider

    @property
    def enabled(self) -> bool:
        if self.provider == "fal":
            return bool(settings.fal_api_key)
        if self.provider == "replicate":
            return bool(settings.replicate_api_token)
        return False

    async def generate(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "4:5",
        negative_prompt: str | None = None,
        seed: int | None = None,
        store: bool = True,
        model: str | None = None,
    ) -> GeneratedImage:
        """Render one image. `model` overrides the configured default so a
        paying tier can be given a better sampler than a trial one."""
        width, height = SIZE_PRESETS.get(aspect_ratio, SIZE_PRESETS["4:5"])
        if not self.enabled:
            raise ConfigurationError(f"image provider '{self.provider}' is not configured")

        prompt = with_constraints(prompt, negative_prompt)
        if self.provider == "fal":
            chosen = model or settings.fal_model
            url = await self._fal(prompt, width, height, seed, chosen)
        elif self.provider == "replicate":
            chosen = settings.replicate_model
            url = await self._replicate(prompt, aspect_ratio, seed)
        else:  # pragma: no cover - guarded by `enabled`
            raise ConfigurationError(f"unknown image provider: {self.provider}")

        image = GeneratedImage(
            url=url, provider=self.provider, width=width, height=height, prompt=prompt
        )
        if store:
            image.stored = await get_storage().save_from_url(url, prefix="flux")
            image.url = image.stored.url
        log.info("image_generated", provider=self.provider, ratio=aspect_ratio, model=chosen)
        return image

    # ------------------------------------------------------------------ #
    async def _fal(
        self, prompt: str, width: int, height: int, seed: int | None, model: str
    ) -> str:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "image_size": {"width": width, "height": height},
            "num_images": 1,
            "enable_safety_checker": True,
            **model_params(model),
        }
        if seed is not None:
            payload["seed"] = seed

        response = await request_with_retry(
            "fal",
            "POST",
            f"https://fal.run/{model}",
            headers={"Authorization": f"Key {settings.fal_api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=180,
        )
        data = response.json()
        images = data.get("images") or []
        if not images or not images[0].get("url"):
            raise ProviderError("fal", "no image in response", details=data, retryable=False)
        return str(images[0]["url"])

    async def _replicate(self, prompt: str, aspect_ratio: str, seed: int | None) -> str:
        headers = {
            "Authorization": f"Bearer {settings.replicate_api_token}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }
        payload: dict[str, Any] = {
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio if aspect_ratio in SIZE_PRESETS else "4:5",
                "output_format": "png",
                "num_outputs": 1,
            }
        }
        if seed is not None:
            payload["input"]["seed"] = seed

        response = await request_with_retry(
            "replicate",
            "POST",
            f"https://api.replicate.com/v1/models/{settings.replicate_model}/predictions",
            headers=headers,
            json=payload,
            timeout=180,
        )
        prediction = response.json()

        # `Prefer: wait` usually returns a finished prediction; poll otherwise.
        client = await get_client("replicate")
        for _ in range(40):
            status = prediction.get("status")
            if status == "succeeded":
                output = prediction.get("output")
                url = output[0] if isinstance(output, list) and output else output
                if not url:
                    raise ProviderError("replicate", "empty output", details=prediction, retryable=False)
                return str(url)
            if status in ("failed", "canceled"):
                raise ProviderError(
                    "replicate", str(prediction.get("error") or status), details=prediction, retryable=False
                )
            await asyncio.sleep(2)
            poll = await client.get(prediction["urls"]["get"], headers=headers)
            prediction = poll.json()

        raise ProviderError("replicate", "prediction timed out", retryable=True)


_generator: ImageGenerator | None = None


def get_image_generator() -> ImageGenerator:
    global _generator
    if _generator is None:
        _generator = ImageGenerator()
    return _generator
