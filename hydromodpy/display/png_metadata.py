"""PNG metadata helpers (tEXt chunks via Pillow).

Embeds provenance info into every PNG saved by HydroModPy figures so a
moved or detached image still carries its ``sim_id``, ``field``, ``time``,
``crs_epsg`` and the runtime version. Readers can inspect the chunks via
``PIL.Image.open(path).info``.

A figure of a run also carries the identity block of that run
(:func:`stamp_png_identity`): a visible footer and a text chunk, posed on
the saved file whatever drew it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.core.version import __version__ as HMP_VERSION
from hydromodpy.results.identity import PNG_IDENTITY_KEY, Identity

SOFTWARE_TAG: str = f"HydroModPy {HMP_VERSION}"


def _string_value(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_text_chunks(
    *,
    sim_id: str | None,
    field: str | None,
    time: str | None,
    crs_epsg: int | None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    chunks: dict[str, str] = {"software": SOFTWARE_TAG, "hmp_version": str(HMP_VERSION)}
    sim_val = _string_value(sim_id)
    if sim_val:
        chunks["sim_id"] = sim_val
    field_val = _string_value(field)
    if field_val:
        chunks["field"] = field_val
    time_val = _string_value(time)
    if time_val:
        chunks["time"] = time_val
    if crs_epsg is not None:
        try:
            chunks["crs_epsg"] = str(int(crs_epsg))
        except (TypeError, ValueError):
            pass
    if extra:
        for key, value in extra.items():
            chunks[str(key)] = str(value)
    return chunks


def _make_pnginfo(chunks: dict[str, str]):
    """Build a Pillow ``PngInfo`` object from a flat ``{key: value}`` dict."""
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    for key, value in chunks.items():
        info.add_text(key, value)
    return info


def write_png_with_metadata(
    fig_or_array,
    path: str | Path,
    *,
    sim_id: str | None = None,
    field: str | None = None,
    time: str | None = None,
    crs_epsg: int | None = None,
    dpi: int = 150,
    extra: dict[str, str] | None = None,
) -> Path:
    """Save ``fig_or_array`` as a PNG with embedded provenance metadata.

    Parameters
    ----------
    fig_or_array
        Either a :class:`matplotlib.figure.Figure` or a 2D ``numpy.ndarray``.
    path
        Output file path. Suffix is forced to ``.png``.
    sim_id, field, time
        Provenance strings written as PNG tEXt chunks.
    crs_epsg
        EPSG integer code stored as a string in the ``crs_epsg`` chunk.
    dpi
        Resolution when saving a matplotlib figure.
    extra
        Additional ``{key: value}`` text chunks.

    Returns
    -------
    Path
        Final on-disk path (suffix forced to ``.png``).
    """
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() != ".png":
        out = out.with_suffix(".png")

    chunks = _build_text_chunks(
        sim_id=sim_id, field=field, time=time, crs_epsg=crs_epsg, extra=extra
    )
    pnginfo = _make_pnginfo(chunks)

    from matplotlib.figure import Figure as MplFigure

    if isinstance(fig_or_array, MplFigure):
        fig_or_array.savefig(
            out,
            dpi=dpi,
            bbox_inches="tight",
            metadata=chunks,
        )
        return out

    array = np.asarray(fig_or_array)
    from PIL import Image

    if array.ndim == 2:
        scaled = _normalize_2d(array)
        image = Image.fromarray(scaled, mode="L")
    elif array.ndim == 3 and array.shape[-1] in (3, 4):
        image = Image.fromarray(array.astype("uint8"))
    else:
        raise ValueError(
            f"Unsupported array shape {array.shape}; expected 2D scalar or HxWx{{3,4}} RGBA."
        )
    image.save(out, format="PNG", pnginfo=pnginfo, optimize=False)
    return out


def _normalize_2d(array: np.ndarray) -> np.ndarray:
    """Map a 2D float array to uint8 [0, 255] for monochrome PNG output."""
    data = np.asarray(array, dtype=float)
    finite = np.isfinite(data)
    if not finite.any():
        return np.zeros(data.shape, dtype="uint8")
    vmin = float(data[finite].min())
    vmax = float(data[finite].max())
    if vmax <= vmin:
        return np.zeros(data.shape, dtype="uint8")
    scaled = np.where(finite, (data - vmin) / (vmax - vmin), 0.0)
    return (np.clip(scaled, 0.0, 1.0) * 255.0).astype("uint8")


def read_png_metadata(path: str | Path) -> dict[str, str]:
    """Return the tEXt chunks stored in the PNG at ``path``."""
    from PIL import Image

    with Image.open(Path(path).expanduser()) as image:
        return dict(image.info or {})


FOOTER_COLOR: tuple[int, int, int] = (90, 90, 90)
"""Gray of the identity footer text."""


def stamp_png_identity(path: str | Path, identity: Identity) -> Path:
    """Pose the identity block in a saved PNG: a visible footer and a text chunk.

    The footer is a strip added under the image, reading
    :meth:`Identity.footer_text`. The block itself goes to the text chunk
    :data:`~hydromodpy.results.identity.PNG_IDENTITY_KEY`, beside the chunks
    the file already holds. A PNG that already carries the chunk keeps its
    footer and gets the new block only, so stamping twice never stacks two
    strips.
    """
    from PIL import Image, ImageDraw, ImageFont

    target = Path(path)
    with Image.open(target) as opened:
        chunks = {str(key): str(value) for key, value in getattr(opened, "text", {}).items()}
        image = opened.copy()
    if PNG_IDENTITY_KEY not in chunks:
        image = _with_footer(image, identity.footer_text(), ImageDraw, ImageFont, Image)
    chunks.update(identity.as_png_metadata())
    image.save(target, format="PNG", pnginfo=_make_pnginfo(chunks), optimize=False)
    return target


def _with_footer(image, text: str, image_draw, image_font, image_module):
    """Return *image* with a white strip below it holding *text*."""
    width, height = image.size
    size = max(10, min(18, width // 90))
    font = image_font.load_default(size=size)
    strip = size * 2
    mode = "RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB"
    background = (255, 255, 255, 255) if mode == "RGBA" else (255, 255, 255)
    framed = image_module.new(mode, (width, height + strip), background)
    framed.paste(image.convert(mode), (0, 0))
    draw = image_draw.Draw(framed)
    text_width = draw.textlength(text, font=font)
    draw.text(
        (max(4, (width - text_width) / 2), height + size // 2),
        text,
        fill=FOOTER_COLOR,
        font=font,
    )
    return framed


__all__ = [
    "FOOTER_COLOR",
    "SOFTWARE_TAG",
    "read_png_metadata",
    "stamp_png_identity",
    "write_png_with_metadata",
]
