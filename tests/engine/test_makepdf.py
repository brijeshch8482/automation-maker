"""pdf.from_files and the Make PDF automation: page order, rotation, page size, margins, size."""

import io
import itertools
from pathlib import Path

import pypdfium2
import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from engine.blocks import makepdf
from engine.errors import EngineError
from engine.loader import load_spec
from engine.smoke import smoke_test
from spec.catalog import PdfFromFilesArgs
from tests.conftest import AUTOMATIONS_DIR
from tests.engine.conftest import write_pdf

MAKE_PDF = AUTOMATIONS_DIR / "make-pdf"
ARGS = PdfFromFilesArgs(files="files", page_size="page_size", margin="margin", smaller="smaller")
MM = 72 / 25.4  # PDF points per mm
RED, BLUE, BLACK, WHITE = (220, 30, 30), (30, 30, 220), (0, 0, 0), (255, 255, 255)


@pytest.fixture
def make_pdf_spec():
    return load_spec(MAKE_PDF / "spec.json")


@pytest.fixture
def build(make_ctx, make_pdf_spec):
    def run(paths, page_size="A4", margin="Small", smaller=False) -> PdfReader:
        inputs = {
            "files": [str(p) for p in paths],
            "page_size": page_size,
            "margin": margin,
            "smaller": smaller,
        }
        doc = makepdf.from_files(make_ctx(inputs=inputs, settings={}, loaded=make_pdf_spec), ARGS)
        assert doc.extension == "pdf"
        return PdfReader(io.BytesIO(doc.data))

    return run


def size_mm(page) -> tuple[float, float]:
    return round(float(page.mediabox.width) / MM, 1), round(float(page.mediabox.height) / MM, 1)


def render(reader: PdfReader, index: int = 0) -> Image.Image:
    out = io.BytesIO()
    writer = PdfWriter()
    writer.add_page(reader.pages[index])
    writer.write(out)
    pdf = pypdfium2.PdfDocument(out.getvalue())
    return pdf[0].render(scale=1).to_pil().convert("RGB")


def near(pixel, colour, tolerance=40) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(pixel, colour, strict=True))


def two_tone(width: int, height: int, top=RED, bottom=BLUE) -> Image.Image:
    image = Image.new("RGB", (width, height), bottom)
    image.paste(top, (0, 0, width, height // 2))
    return image


# --- the catalog automation ------------------------------------------------------------------


def test_sample_data_makes_three_pages_in_order(build):
    samples = MAKE_PDF / "samples"
    reader = build(
        [samples / "Receipt photo.jpg", samples / "Screenshot.png", samples / "Notes.pdf"]
    )
    assert len(reader.pages) == 3
    assert size_mm(reader.pages[0]) == (210.0, 297.0)  # the sideways phone photo, upright
    assert size_mm(reader.pages[1]) == (297.0, 210.0)  # the wide screenshot: landscape A4
    assert "Notes (sample)" in reader.pages[2].extract_text()
    assert reader.metadata["/Creator"] == "MakeMyEXE"


def test_smoke_test_passes_and_leaves_samples_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKEMYEXE_DATA_DIR", str(tmp_path / "data"))
    samples = sorted((MAKE_PDF / "samples").iterdir())
    before = {p.name: p.read_bytes() for p in samples}
    report = smoke_test(load_spec(MAKE_PDF / "spec.json"), tmp_path / "out")
    assert report["status"] == "passed", report
    assert {p.name: p.read_bytes() for p in samples} == before


def test_every_option_in_the_spec_is_accepted(build, make_pdf_spec, tmp_path):
    photo = tmp_path / "p.jpg"
    two_tone(60, 80).save(photo)
    options = {f.key: f.options for f in make_pdf_spec.spec.inputs if f.type == "select"}
    assert set(options) == {"page_size", "margin"}
    for page_size, margin, smaller in itertools.product(
        options["page_size"], options["margin"], [True, False]
    ):
        assert len(build([photo], page_size, margin, smaller).pages) == 1


# --- photos ---------------------------------------------------------------------------------


def test_exif_rotated_phone_photo_comes_out_upright(build, tmp_path):
    upright = two_tone(300, 400)  # red on top
    stored = upright.rotate(90, expand=True)  # how the camera saved it: sideways
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90° clockwise to view"
    photo = tmp_path / "phone.jpg"
    stored.save(photo, exif=exif)
    reader = build([photo], margin="None")
    assert size_mm(reader.pages[0]) == (210.0, 297.0)
    page = render(reader)
    assert near(page.getpixel((page.width // 2, page.height // 2 - 60)), RED)
    assert near(page.getpixel((page.width // 2, page.height // 2 + 60)), BLUE)


def test_transparent_screenshot_gets_a_white_background(build, tmp_path):
    shot = Image.new("RGBA", (200, 100), (0, 0, 0, 0))  # transparent black
    shot.paste((30, 30, 220, 255), (80, 30, 120, 70))
    path = tmp_path / "shot.png"
    shot.save(path)
    page = render(build([path], page_size="Same as each photo", margin="None"))
    assert near(page.getpixel((3, 3)), WHITE, 10)
    assert near(page.getpixel((page.width // 2, page.height // 2)), BLUE)


def test_page_follows_photo_orientation_and_paper(build, tmp_path):
    wide, tall = tmp_path / "wide.png", tmp_path / "tall.png"
    two_tone(400, 300).save(wide)
    two_tone(300, 400).save(tall)
    reader = build([wide, tall], page_size="Letter")
    assert size_mm(reader.pages[0]) == (279.4, 215.9)
    assert size_mm(reader.pages[1]) == (215.9, 279.4)


def test_same_as_each_photo_sizes_the_page_to_the_photo(build, tmp_path):
    photo = tmp_path / "p.png"
    two_tone(400, 200).save(photo)
    # 400 x 200 px at 200 dpi = 50.8 x 25.4 mm, plus a small (6 mm) border on each side.
    assert size_mm(build([photo], page_size="Same as each photo").pages[0]) == (62.8, 37.4)
    assert size_mm(build([photo], page_size="Same as each photo", margin="None").pages[0]) == (
        50.8,
        25.4,
    )


def test_margin_leaves_a_white_border(build, tmp_path):
    photo = tmp_path / "black.png"
    Image.new("RGB", (210, 297), BLACK).save(photo)  # A4 shape: fills the page without margin
    for margin, edge in [("None", BLACK), ("Normal", WHITE)]:
        page = render(build([photo], margin=margin))
        x = round(5 * MM)  # 5 mm from the left edge, halfway down
        assert near(page.getpixel((x, page.height // 2)), edge, 10), margin


def test_big_photos_are_scaled_to_print_quality(build, tmp_path):
    photo = tmp_path / "big.png"
    two_tone(4000, 3000).save(photo)
    image = build([photo]).pages[0].images[0].image
    # Landscape A4 inside 6 mm borders is 285 x 198 mm; a 4:3 photo fills the height:
    # 198 mm at 200 dpi is about 1559 px.
    assert image.size == (2079, 1559)


def test_screenshots_stay_sharp_photos_are_jpeg(build, tmp_path):
    png, jpg = tmp_path / "s.png", tmp_path / "p.jpg"
    two_tone(300, 200).save(png)
    two_tone(300, 200).save(jpg)
    reader = build([png, jpg])
    assert reader.pages[0].images[0].name.endswith(".png")  # lossless, no JPEG blur on text
    assert reader.pages[1].images[0].name.endswith(".jpg")
    smaller = build([png], smaller=True)
    assert smaller.pages[0].images[0].name.endswith(".jpg")


def test_smaller_option_makes_a_smaller_file(make_ctx, make_pdf_spec, tmp_path):
    photo = tmp_path / "noisy.jpg"
    Image.effect_noise((2400, 1800), 60).convert("RGB").save(photo, quality=95)

    def size(smaller) -> int:
        inputs = {"files": [str(photo)], "smaller": smaller}  # unset options use defaults
        ctx = make_ctx(inputs=inputs, settings={}, loaded=make_pdf_spec)
        return len(makepdf.from_files(ctx, ARGS).data)

    assert size("true") < size(False) * 0.75


def test_every_page_of_a_multi_page_tiff(build, tmp_path):
    scan = tmp_path / "scan.tiff"
    pages = [two_tone(100, 140, top=c) for c in (RED, BLUE, BLACK)]
    pages[0].save(scan, save_all=True, append_images=pages[1:])
    assert len(build([scan]).pages) == 3


def test_heic_iphone_photo(build, tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    photo = tmp_path / "IMG_0001.HEIC"
    try:
        pillow_heif.from_pillow(two_tone(120, 160)).save(photo, quality=90)
    except (RuntimeError, ValueError, OSError) as err:  # wheel built without an HEVC encoder
        pytest.skip(f"cannot write HEIC here: {err}")
    reader = build([photo], margin="None")
    assert size_mm(reader.pages[0]) == (210.0, 297.0)
    page = render(reader)
    assert near(page.getpixel((page.width // 2, page.height // 4)), RED, 60)


def test_originals_are_only_read(build, tmp_path):
    folder = tmp_path / "mine"
    folder.mkdir()
    photo, pdf = folder / "p.jpg", write_pdf(folder / "doc.pdf", 2)
    two_tone(300, 400).save(photo)
    before = {p: p.read_bytes() for p in (photo, pdf)}
    reader = build([pdf, photo, pdf])
    assert len(reader.pages) == 5
    assert {p: p.read_bytes() for p in (photo, pdf)} == before
    assert sorted(p.name for p in folder.iterdir()) == ["doc.pdf", "p.jpg"]  # nothing added


# --- errors (never name the user's files or values) -------------------------------------------


def test_errors(build, tmp_path, monkeypatch):
    with pytest.raises(EngineError, match="at least one"):
        build([])
    notes = tmp_path / "secret-notes.txt"
    notes.write_text("hello")
    with pytest.raises(EngineError, match="file 1 is not a photo or PDF") as err:
        build([notes])
    assert "secret" not in str(err.value)
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not really a photo")
    good = tmp_path / "good.png"
    two_tone(50, 50).save(good)
    with pytest.raises(EngineError, match="file 2 could not be read as a photo"):
        build([good, broken])
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"not a pdf")
    with pytest.raises(EngineError, match="file 1 could not be read as a PDF"):
        build([bad_pdf])
    locked = tmp_path / "locked.pdf"
    writer = PdfWriter(clone_from=write_pdf(tmp_path / "plain.pdf", 1))
    writer.encrypt("secret")
    writer.write(locked)
    with pytest.raises(EngineError, match="file 1 is password-protected"):
        build([locked])
    with pytest.raises(EngineError, match="unknown page size"):
        build([good], page_size="A3")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(EngineError, match="file 1 is too large"):
        build([good])


def test_missing_file_is_reported_by_number(build, tmp_path):
    with pytest.raises(EngineError, match="file 1 could not be read as a photo"):
        build([Path(tmp_path / "gone.jpg")])
