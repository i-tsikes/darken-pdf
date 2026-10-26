#!/usr/bin/env python3
from pdf2image import convert_from_path
from PIL import Image, ImageEnhance
import numpy as np
import pytesseract
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import argparse
import io
import os
import sys


def parse_args():
    parser = argparse.ArgumentParser(
        description="Darken text in a PDF and add an invisible OCR text layer."
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
        help="Percent darkening of the text as an integer 0–100 (default: 100%% black)",
    )
    return parser.parse_args()


def resolve_output_path(pdf_path, output_arg):
    if output_arg:
        return output_arg
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    return os.path.join(os.getcwd(), f"{stem}-darker.pdf")


def text_gray_level(darken_percent):
    """Map darkening percent to an RGB gray value (100%% → black, 0%% → white)."""
    percent = 100 if darken_percent is None else darken_percent
    if percent < 0 or percent > 100:
        raise ValueError(f"Darkening percent must be between 0 and 100, got {percent}")
    return int(round(255 * (1 - percent / 100.0)))


def main():
    args = parse_args()
    pdf_path = args.pdf
    output_path = resolve_output_path(pdf_path, args.output)

    try:
        gray = text_gray_level(args.darken)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    if not os.path.isfile(pdf_path):
        print(f"error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    print("Converting pages...")
    images = convert_from_path(pdf_path, dpi=150)

    c = None
    for i, img in enumerate(images):
        print(f"Processing page {i+1}/{len(images)}...")
        # Darken text
        enhancer = ImageEnhance.Contrast(img)
        img_c = enhancer.enhance(2.8)
        arr = np.array(img_c)
        brightness = np.mean(arr, axis=2)
        mask = brightness < 170
        arr[mask] = [gray, gray, gray]
        proc_img = Image.fromarray(arr)

        # Page size in points
        scale = 72 / 150
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
        data = pytesseract.image_to_data(proc_img, output_type=pytesseract.Output.DICT)
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
