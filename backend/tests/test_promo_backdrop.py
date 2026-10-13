"""The backdrop layer, which was wired end to end and rendered nothing.

`backdrops.py` drew six motifs, `template.html` created an `<img id=bg>` for
`S.background` and even panned it, and `_localise` resolved its path. Every
piece worked. Every archetype also declares `grid.bg`, and the `.gridbg` div
that draws is `inset:0` with an opaque brand fill — so the picture was painted
and then covered, on every clip, in full.

Nothing caught it because nothing looked at pixels: the script had the key, the
DOM had the element, the image reported `naturalWidth: 1080`. Only the frame
disagreed. So these tests compare rendered output, and are the only kind that
could have failed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.backdrops import generate_library
from app.services.promo_families import Brand

pytestmark = pytest.mark.chromium

BRAND = {"bg": "#0B0F14", "accent": "#2FD9C4"}


def _script(use: str, text: dict, background: str = ""):
    from app.services.promo_scenes import build_script

    job = {
        "name": "backdrop-test", "mood": "tezkor",
        "scenes": [{"use": use, "slot": "s0", "say": 0}],
        "say": ["Kompaniyalarning yetmish foizi shu xatoni qiladi."],
        "text": {"s0": text},
    }
    if background:
        job["background"] = background
    return build_script(job, Brand.from_colors(BRAND, mark="Sinov", cta="Yozing"))


async def _cover(script):
    from PIL import Image

    from app.services.promo import _capture, _localise

    with tempfile.TemporaryDirectory() as tmp:
        _, cover = await _capture(_localise(script), Path(tmp))
        path = Path(tmp) / "cover.jpg"
        path.write_bytes(cover)
        return Image.open(path).convert("RGB").copy()


def _accent_pixels(image) -> int:
    """Pixels carrying the motif's colour. The motifs are drawn in the brand
    accent, which nothing else in a `stat` scene uses at this saturation."""
    return sum(1 for r, g, b in image.getdata() if g > r + 15 and g > 35)


@pytest.fixture(scope="module")
def library(tmp_path_factory) -> list[Path]:
    target = tmp_path_factory.mktemp("backdrops")
    return generate_library(target, BRAND, prefix="bg")


class TestTheBackdropReachesTheFrame:
    async def test_a_dark_scene_shows_the_picture(self, library):
        """The failing case: identical pixels with and without a backdrop."""
        stat = {"label": "Xato", "to": 70, "suffix": "%"}
        without = await _cover(_script("stat", stat))
        with_bg = await _cover(_script("stat", stat, str(library[2])))
        assert _accent_pixels(with_bg) > _accent_pixels(without) + 2000

    async def test_the_scrim_holds_it_back_rather_than_letting_it_shout(self, library):
        """A backdrop at full strength is a legibility problem, not a feature."""
        from PIL import Image

        source = Image.open(library[2]).convert("RGB")
        rendered = await _cover(_script("stat", {"label": "Xato", "to": 70},
                                        str(library[2])))
        # Visible, but well under the raw motif — the fill became a scrim, not
        # a hole.
        assert 0.05 < _accent_pixels(rendered) / _accent_pixels(source) < 0.5

    async def test_an_authored_light_panel_stays_opaque(self, library):
        """`sarlavha` and friends are white cards on purpose.

        Letting a photograph through them would not be variety, it would be
        the card ceasing to be a card. Only the dark brand fill scrims.
        """
        lines = {"lines": [{"text": "BIR"}, {"text": "IKKI"}]}
        without = await _cover(_script("sarlavha", lines))
        with_bg = await _cover(_script("sarlavha", lines, str(library[2])))
        assert abs(_accent_pixels(with_bg) - _accent_pixels(without)) < 500

    async def test_two_motifs_do_not_render_the_same_frame(self, library):
        """Rotation is pointless if the pictures are indistinguishable."""
        from PIL import ImageChops

        stat = {"label": "Xato", "to": 70, "suffix": "%"}
        first = await _cover(_script("stat", stat, str(library[0])))
        third = await _cover(_script("stat", stat, str(library[2])))
        assert ImageChops.difference(first, third).getbbox() is not None
