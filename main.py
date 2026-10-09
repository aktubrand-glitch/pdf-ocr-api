
import os
import time
from io import BytesIO

import fitz
import pytesseract
from PIL import Image
from fastapi import FastAPI, File, Header, HTTPException, UploadFile


app = FastAPI(title="English and Hindi PDF OCR API", version="1.0.0")

MAX_PAGES = 20
MAX_FILE_SIZE = 15 * 1024 * 1024
OCR_LANGUAGE = "eng+hin"
API_KEY = os.getenv("API_KEY", "")


def check_api_key(authorization: str | None):
    if not API_KEY:
        raise HTTPException(
            status_code=503,
            detail="API_KEY is not configured on the server."
        )

    #if authorization != f"Bearer {API_KEY}":
       # raise HTTPException(status_code=401, detail="Invalid API key")


def extract_pdf(data: bytes) -> dict:
    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid, damaged, or unreadable PDF."
        )

    try:
        if pdf.is_encrypted:
            raise HTTPException(
                status_code=400,
                detail="Password-protected PDFs are not supported."
            )

        page_count = len(pdf)

        if page_count == 0:
            raise HTTPException(status_code=400, detail="PDF is empty.")

        if page_count > MAX_PAGES:
            raise HTTPException(
                status_code=413,
                detail=f"PDF contains {page_count} pages. "
                       f"Maximum allowed is {MAX_PAGES}."
            )

        page_results = []
        all_text = []

        for index, page in enumerate(pdf):
            text = page.get_text("text").strip()
            method = "embedded_text"

            # OCR pages that have little selectable text.
            if len(text) < 40:
                try:
                    pix = page.get_pixmap(
                        matrix=fitz.Matrix(1.5, 1.5),
                        colorspace=fitz.csRGB,
                        alpha=False,
                    )

                    image_bytes = pix.tobytes("png")

                    with Image.open(BytesIO(image_bytes)) as image:
                        text = pytesseract.image_to_string(
                            image,
                            lang=OCR_LANGUAGE,
                            timeout=45,
                        ).strip()

                    method = "tesseract_ocr"

                except RuntimeError:
                    raise HTTPException(
                        status_code=422,
                        detail=f"OCR timed out on page {index + 1}."
                    )
                except Exception as exc:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Could not process page {index + 1}. "
                               f"Check that OCR language data is installed."
                    )

            page_results.append({
                "page": index + 1,
                "method": method,
                "text": text,
            })

            all_text.append(text)

        return {
            "success": True,
            "pages": page_count,
            "languages": ["English", "Hindi"],
            "text": "\n\n".join(all_text),
            "page_results": page_results,
        }

    finally:
        pdf.close()


@app.get("/")
def home():
    return {
        "service": "PDF OCR API",
        "status": "running",
        "endpoint": "POST /extract-text",
        "max_pages": MAX_PAGES,
        "max_file_size_mb": MAX_FILE_SIZE // (1024 * 1024),
        "languages": ["English", "Hindi"],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/extract-text")
async def extract_text(
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
):
    check_api_key(authorization)

    if file.content_type not in (
        "application/pdf",
        "application/octet-stream",
    ):
        raise HTTPException(
            status_code=400,
            detail="Upload a PDF file using multipart/form-data."
        )

    try:
        data = await file.read(MAX_FILE_SIZE + 1)
    finally:
        await file.close()

    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="PDF exceeds the 15 MB limit."
        )

    if not data.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is not a valid PDF."
        )

    started = time.time()
    result = extract_pdf(data)
    result["processing_seconds"] = round(time.time() - started, 2)

    return result
