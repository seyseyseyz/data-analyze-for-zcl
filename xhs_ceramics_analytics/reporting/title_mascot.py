"""Self-contained title mascot shared by every HTML report renderer."""

from base64 import b64encode
from functools import lru_cache
from importlib.resources import files


TITLE_MASCOT_CSS = """
    .title-mascot {
      display: inline-block;
      width: auto;
      height: 52px;
      margin-left: 0.16em;
      position: relative;
      top: 2px;
      vertical-align: -0.14em;
      object-fit: contain;
      image-rendering: pixelated;
    }
    .title-mascot--still { display: none; }
    @media (max-width: 700px) {
      .title-mascot { height: 44px; }
    }
    @media (prefers-reduced-motion: reduce), print {
      .title-mascot--animated { display: none; }
      .title-mascot--still { display: inline-block; }
    }
"""


@lru_cache(maxsize=2)
def _data_uri(filename: str, media_type: str) -> str:
    asset = files("xhs_ceramics_analytics.reporting").joinpath("assets", filename)
    payload = b64encode(asset.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{payload}"


@lru_cache(maxsize=1)
def title_mascot_html() -> str:
    """Return stable inline markup while keeping the generated report offline."""
    animated = _data_uri("title-mascot-loop.gif", "image/gif")
    still = _data_uri("title-mascot-still.png", "image/png")
    return (
        '<img class="title-mascot title-mascot--animated" '
        f'src="{animated}" alt="旋转的小熊" width="164" height="136">'
        '<img class="title-mascot title-mascot--still" '
        f'src="{still}" alt="小熊" width="164" height="136">'
    )


def attach_title_mascot(html: str) -> str:
    """Attach the mascot to the first document title without changing its text."""
    return html.replace("</h1>", f"{title_mascot_html()}</h1>", 1)
