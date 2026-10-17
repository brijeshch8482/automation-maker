"""pdf.from_files: one PDF from photos, screenshots, scans and existing PDFs, in order.

Originals are only read. Photos are turned upright (EXIF orientation), flattened onto white,
scaled down to print quality and placed on A4, Letter or a page the size of the photo.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pillow_heif
from fpdf import FPDF
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from engine.context import RunContext
from engine.errors import EngineError
from engine.values import Document
from spec.catalog import PdfFromFilesArgs

pillow_heif.register_heif_opener()  # iPhone photos (.heic / .heif)

PHOTO_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "gif", "heic", "heif"}
# Lossless sources are usually screenshots or scans with text: keep them sharp (PNG in the PDF).
LOSSLESS_FORMATS = {"PNG", "GIF", "BMP"}

PAGE_SIZES_MM = {"a4": (210.0, 297.0), "letter": (215.9, 279.4)}
PAGE_SIZE_NAMES = {
    "a4": "a4",
    "letter": "letter",
    "same as each photo": "fit",
    "photo size": "fit",
    "fit": "fit",
}
MARGINS_MM = {"none": 0.0, "small": 6.0, "normal": 12.0}

NORMAL = {"dpi": 200, "jpeg_quality": 85, "max_px": 3000}
SMALLER = {"dpi": 150, "jpeg_quality": 72, "max_px": 2000}
MM_PER_INCH = 25.4


def from_files(ctx: RunContext, args: PdfFromFilesArgs) -> Document:
    paths = [Path(p) for p in ctx.value(args.files) or []]
    if not paths:
        raise EngineError("choose at least one photo, screenshot or PDF")
    page = _choice(ctx, args.page_size, PAGE_SIZE_NAMES, "a4", "page size")
    margin = MARGINS_MM[_choice(ctx, args.margin, {k: k for k in MARGINS_MM}, "small", "margin")]
    quality = SMALLER if _flag(ctx, args.smaller) else NORMAL

    writer = PdfWriter()
    for n, path in enumerate(paths, start=1):
        extension = path.suffix.lower().lstrip(".")
        if extension == "pdf":
            _append_pdf(writer, path, n)
        elif extension in PHOTO_EXTENSIONS:
            for frame, lossless in _frames(path, n):
                page_pdf = _photo_page(frame, lossless, page, margin, quality)
                writer.append(PdfReader(io.BytesIO(page_pdf)))
        else:
            raise EngineError(f"file {n} is not a photo or PDF this app can read")
    out = io.BytesIO()
    writer.add_metadata({"/Creator": "MakeMyEXE"})
    writer.write(out)
    return Document(out.getvalue(), "pdf")


def _choice(
    ctx: RunContext, ref: str | None, names: dict[str, str], default: str, what: str
) -> str:
    raw = ctx.value(ref) if ref else None
    if raw is None or str(raw).strip() == "":
        return default
    key = str(raw).strip().lower()
    if key not in names:
        raise EngineError(f"unknown {what}")
    return names[key]


def _flag(ctx: RunContext, ref: str | None) -> bool:
    raw: Any = ctx.value(ref) if ref else False
    if isinstance(raw, str):
        return raw.strip().lower() in {"true", "yes", "1"}
    return bool(raw)


def _append_pdf(writer: PdfWriter, path: Path, n: int) -> None:
    try:
        reader = PdfReader(path)  # read only; the original is never changed
        if reader.is_encrypted:
            raise EngineError(f"file {n} is password-protected")
        writer.append(reader)
    except (OSError, PdfReadError) as err:
        raise EngineError(f"file {n} could not be read as a PDF") from err


def _frames(path: Path, n: int):
    """Yield (RGB image, lossless?) per page: every page of a multi-page TIFF, else one."""
    try:
        with Image.open(path) as image:
            lossless = image.format in LOSSLESS_FORMATS
            frames = ImageSequence.Iterator(image) if image.format == "TIFF" else [image]
            for frame in frames:
                yield _flatten(ImageOps.exif_transpose(frame.copy())), lossless
    except Image.DecompressionBombError as err:
        raise EngineError(f"file {n} is too large to put in a PDF") from err
    except (UnidentifiedImageError, OSError, ValueError) as err:
        raise EngineError(f"file {n} could not be read as a photo") from err


def _flatten(image: Image.Image) -> Image.Image:
    """RGB on white: transparent screenshots and logos don't turn black."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        white = Image.new("RGB", rgba.size, (255, 255, 255))
        white.paste(rgba, mask=rgba.getchannel("A"))
        return white
    return image.convert("RGB")


def _photo_page(
    image: Image.Image, lossless: bool, page: str, margin: float, quality: dict[str, int]
) -> bytes:
    dpi = quality["dpi"]
    if page == "fit":
        image = _limit(image, quality["max_px"])
        width = image.width * MM_PER_INCH / dpi
        height = image.height * MM_PER_INCH / dpi
        page_w, page_h = width + 2 * margin, height + 2 * margin
    else:
        short, long = PAGE_SIZES_MM[page]
        landscape = image.width > image.height
        page_w, page_h = (long, short) if landscape else (short, long)
        box_w, box_h = page_w - 2 * margin, page_h - 2 * margin
        scale = min(box_w / image.width, box_h / image.height)
        width, height = image.width * scale, image.height * scale
        # Never keep more pixels than the page can show at this dpi (keeps the PDF small).
        target = round(max(width, height) / MM_PER_INCH * dpi)
        image = _limit(image, min(target, quality["max_px"]))

    data = io.BytesIO()
    if lossless and quality is NORMAL:
        image.save(data, "PNG", optimize=True)
    else:
        image.save(data, "JPEG", quality=quality["jpeg_quality"], optimize=True)

    pdf = FPDF(unit="mm", format=(page_w, page_h))
    pdf.set_auto_page_break(False)
    pdf.set_margins(0, 0, 0)
    pdf.add_page()
    pdf.image(data, x=(page_w - width) / 2, y=(page_h - height) / 2, w=width, h=height)
    return bytes(pdf.output())


def _limit(image: Image.Image, longest: int) -> Image.Image:
    if max(image.size) <= longest:
        return image
    resized = image.copy()
    resized.thumbnail((longest, longest), Image.Resampling.LANCZOS)
    return resized
