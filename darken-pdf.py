from pdf2image import convert_from_path
from PIL import Image, ImageEnhance
import numpy as np
import pytesseract
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import io
import os

pdf_path = "projectile-ballistics-discussion-and-code.pdf"  # ← change if needed
output_path = "projectile-ballistics-darker-ocr.pdf"

print("Converting pages...")
images = convert_from_path(pdf_path, dpi=150)

c = None
for i, img in enumerate(images):
    print(f"Processing page {i+1}/{len(images)}...")
    # Darken text to very dark gray
    enhancer = ImageEnhance.Contrast(img)
    img_c = enhancer.enhance(2.8)
    arr = np.array(img_c)
    brightness = np.mean(arr, axis=2)
    mask = brightness < 170
    arr[mask] = [32, 32, 32]
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
            except:
                pass

c.save()
print(f"Done → {output_path}")
