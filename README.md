# python-utils

Small Python utilities. Managed with [uv](https://docs.astral.sh/uv/).

## Setup

```bash
uv sync
```

### System dependencies

`darken-pdf.py` needs native tools that **uv does not install**:

| Tool | Used for | Homebrew | apt |
|------|----------|----------|-----|
| `tesseract` | OCR text layer (`pytesseract`) | `brew install tesseract` | `sudo apt-get install -y tesseract-ocr` |
| `poppler` (`pdftoppm`) | PDF → images (`pdf2image`) | `brew install poppler` | `sudo apt-get install -y poppler-utils` |

```bash
# macOS
brew install tesseract poppler

# Ubuntu / Debian
sudo apt-get install -y tesseract-ocr poppler-utils
```

If tesseract is installed but not on your shell `PATH` (common with Homebrew in some IDEs), the script also looks in `/opt/homebrew/bin` and `/usr/local/bin`.

## darken-pdf

Darkens text in a PDF and adds an invisible OCR text layer.

```bash
uv run -- darken-pdf.py input.pdf
uv run -- darken-pdf.py input.pdf -o /tmp/out.pdf -d 87
./run.sh input.pdf -o out.pdf -d 100
```

- First argument: input PDF
- `-o`: output path (default: `<stem>-darker.pdf` in the current directory)
- `-d`: text darkening percent `0`–`100` (default: 100% black)
