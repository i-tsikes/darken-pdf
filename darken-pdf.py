#!/usr/bin/env -S uv run
from pdf2image import convert_from_path
from pdf2image.exceptions import PDFInfoNotInstalledError
from PIL import Image, ImageFilter
import numpy as np
import pytesseract
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import argparse
import io
import os
import shutil
import sys

DEFAULT_DPI = 200


TESSERACT_CANDIDATES = (
    "tesseract",
    "/opt/homebrew/bin/tesseract",  # Apple Silicon Homebrew
    "/usr/local/bin/tesseract",  # Intel Homebrew / Linux local
    "/usr/bin/tesseract",
)

POPPLER_CANDIDATES = (
    "pdftoppm",
    "/opt/homebrew/bin/pdftoppm",
    "/usr/local/bin/pdftoppm",
    "/usr/bin/pdftoppm",
)

SYSTEM_DEPS_HELP = """\
This script needs two system tools (not installed by uv):

  • tesseract  — OCR engine used by pytesseract
  • poppler    — PDF rasterizer used by pdf2image (pdftoppm)

Install them, then re-run:

  macOS (Homebrew):
    brew install tesseract poppler

  Ubuntu / Debian:
    sudo apt-get install -y tesseract-ocr poppler-utils

  Fedora:
    sudo dnf install -y tesseract poppler-utils
"""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Darken text in a PDF and add an invisible OCR text layer.",
        epilog=SYSTEM_DEPS_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "pdf",
        help="PDF file to modify",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output file path (default: <input-stem>-darker.pdf in the current directory)",
    )
    parser.add_argument(
        "-d",
        "--darken",
        type=int,
        default=None,
        metavar="PERCENT",
        help="Darkening strength 0–100 (default: 100). Higher values pull faint "
        "strokes/equations closer to black while trying to preserve figure shading.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"Rasterization DPI (default: {DEFAULT_DPI}). Higher helps fine equations.",
    )
    return parser.parse_args()


def resolve_output_path(pdf_path, output_arg):
    if output_arg:
        return output_arg
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    return os.path.join(os.getcwd(), f"{stem}-darker.pdf")


def darken_strength(darken_percent):
    """Map -d percent to a 0..1 strength (default 100 → 1.0)."""
    percent = 100 if darken_percent is None else darken_percent
    if percent < 0 or percent > 100:
        raise ValueError(f"Darkening percent must be between 0 and 100, got {percent}")
    return percent / 100.0


def darken_page(im: Image.Image, strength: float = 1.0) -> Image.Image:
    """Darken faint strokes/equations while preserving smooth figure shading.

    The old approach (global contrast + hard threshold → flat black) left light
    anti-aliased math unchanged and crushed shaded figures into solid blobs.
    This instead scores ink-like pixels (darker than local paper / faint on white)
    and pulls those toward black, while protecting low-contrast smooth regions.
    """
    strength = float(np.clip(strength, 0.0, 1.0))
    if strength <= 0:
        return im.copy()

    # Reinforce hairlines without the global contrast blowout that washes figures.
    sharp = im.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=2))
    arr = np.asarray(sharp, dtype=np.float32)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    arr = arr[:, :, :3]

    luma = arr.mean(axis=2)
    blur = np.asarray(
        Image.fromarray(luma.astype(np.uint8)).filter(ImageFilter.BoxBlur(3)),
        dtype=np.float32,
    )

    # Ink cues: darker than local paper, or light-gray on white paper (equations).
    stroke = np.clip((blur - luma) / 28.0, 0.0, 1.0)
    paper = blur > 220
    faint = paper & (luma < 235) & (luma > 15)
    faint_score = faint.astype(np.float32) * np.clip((235.0 - luma) / 90.0, 0.0, 1.0)

    local_contrast = np.abs(blur - luma)
    smooth = (local_contrast < 12.0) & (luma < 240.0)

    ink = np.clip(np.maximum(stroke, 1.25 * faint_score), 0.0, 1.0)
    ink = np.where(smooth, ink * 0.22, ink)

    content = np.clip((248.0 - luma) / 248.0, 0.0, 1.0)
    amount = np.clip(strength * ink * (0.35 + 0.65 * ink), 0.0, 1.0)
    # Mild nudge for medium body text that may have a low stroke score.
    amount = np.clip(amount + strength * 0.35 * np.power(content, 1.8), 0.0, 1.0)
    amount = np.where(luma >= 245, 0.0, amount)

    pull = 0.55 + 0.45 * ink
    factor = np.clip(1.0 - amount * pull, 0.0, 1.0)
    factor = np.where(luma >= 245, 1.0, factor)
    out_arr = arr * factor[..., None]

    # Slightly thicken strong ink (helps hairline math) without filling figures.
    gray = np.clip(out_arr.mean(axis=2), 0, 255).astype(np.uint8)
    thick = np.asarray(Image.fromarray(gray).filter(ImageFilter.MinFilter(3)))
    grow = (ink > 0.40) & (~smooth) & (gray < 210) & (luma < 245)
    gray_out = gray.copy()
    gray_out[grow] = np.minimum(gray[grow], thick[grow])

    strong = (ink > 0.50) & (~smooth) & (luma < 245)
    for c in range(3):
        channel = out_arr[:, :, c]
        channel[strong] = gray_out[strong]
        out_arr[:, :, c] = channel

    return Image.fromarray(np.clip(out_arr, 0, 255).astype(np.uint8))


def find_executable(candidates):
    for candidate in candidates:
        if os.path.isabs(candidate):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


def ensure_system_deps():
    """Locate tesseract/poppler and configure pytesseract; exit with help if missing."""
    tesseract = find_executable(TESSERACT_CANDIDATES)
    pdftoppm = find_executable(POPPLER_CANDIDATES)

    missing = []
    if not tesseract:
        missing.append("tesseract")
    if not pdftoppm:
        missing.append("poppler (pdftoppm)")

    if missing:
        print(
            f"error: missing system dependenc{'y' if len(missing) == 1 else 'ies'}: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        print(file=sys.stderr)
        print(SYSTEM_DEPS_HELP, file=sys.stderr)
        sys.exit(1)

    pytesseract.pytesseract.tesseract_cmd = tesseract
    # pdf2image finds poppler via PATH; if only a non-PATH install exists, put its
    # directory first so convert_from_path can call pdftoppm.
    poppler_dir = os.path.dirname(pdftoppm)
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if poppler_dir and poppler_dir not in path_dirs:
        os.environ["PATH"] = poppler_dir + os.pathsep + os.environ.get("PATH", "")

    return tesseract, pdftoppm


def main():
    args = parse_args()
    pdf_path = args.pdf
    output_path = resolve_output_path(pdf_path, args.output)

    try:
        strength = darken_strength(args.darken)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.dpi <= 0:
        print(f"error: --dpi must be positive, got {args.dpi}", file=sys.stderr)
        sys.exit(2)

    if not os.path.isfile(pdf_path):
        print(f"error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    ensure_system_deps()

    print("Converting pages...")
    try:
        images = convert_from_path(pdf_path, dpi=args.dpi)
    except PDFInfoNotInstalledError:
        print("error: poppler is not available (pdftoppm/pdfinfo missing).", file=sys.stderr)
        print(file=sys.stderr)
        print(SYSTEM_DEPS_HELP, file=sys.stderr)
        sys.exit(1)

    c = None
    for i, img in enumerate(images):
        print(f"Processing page {i+1}/{len(images)}...")
        proc_img = darken_page(img, strength=strength)

        # Page size in points
        scale = 72 / args.dpi
        page_w = proc_img.width * scale
        page_h = proc_img.height * scale

        if c is None:
            c = canvas.Canvas(output_path, pagesize=(page_w, page_h))
        else:
            c.showPage()
            c.setPageSize((page_w, page_h))

        # Draw darkened image
        buf = io.BytesIO()
        proc_img.save(buf, format="PNG")
        buf.seek(0)
        c.drawImage(ImageReader(buf), 0, 0, width=page_w, height=page_h)

        # OCR overlay (invisible white text)
        try:
            data = pytesseract.image_to_data(
                proc_img, output_type=pytesseract.Output.DICT
            )
        except pytesseract.TesseractNotFoundError:
            print("error: tesseract is not installed or not on PATH.", file=sys.stderr)
            print(file=sys.stderr)
            print(SYSTEM_DEPS_HELP, file=sys.stderr)
            sys.exit(1)

        for j in range(len(data["text"])):
            if int(data["conf"][j]) > 50 and data["text"][j].strip():
                x = data["left"][j] * scale
                y = page_h - (data["top"][j] + data["height"][j]) * scale
                font_size = max(6, data["height"][j] * scale * 0.75)
                c.setFillColorRGB(1, 1, 1)
                c.setFont("Helvetica", font_size)
                try:
                    c.drawString(x, y, data["text"][j])
                except Exception:
                    pass

    c.save()
    print(f"Done → {output_path}")


if __name__ == "__main__":
    main()
