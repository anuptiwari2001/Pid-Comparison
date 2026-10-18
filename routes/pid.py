"""
P&ID routes — equivalent of TypeScript routes/pid/index.ts

POST /api/pid/upload   — upload two PDFs and convert them to images
POST /api/pid/compare  — full pipeline: convert → AI analysis → PDF report
GET  /api/pid/report/{report_id} — download the generated PDF report
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from lib.markup_analyzer import analyze_pid_markup
from lib.pdf_converter import cleanup_temp_dir, pdf_to_images
from lib.report_generator import generate_pdf_report
from lib.store import get_annotated_pdf, get_report, save_annotated_pdf, save_report
from lib.types import ApiError, ComparisonResult, UploadResult
from lib.visual_annotator import generate_annotated_overlay_pdf

log = logging.getLogger("pid_api")
router = APIRouter(tags=["pid"])

UPLOADS_DIR = Path("uploads")
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
HARD_PAGE_CAP = 10


async def _save_upload(file: UploadFile, dest_dir: Path) -> Path:
    """Save an uploaded file to dest_dir and return the saved path."""
    safe_name = Path(file.filename or "upload.pdf").name
    dest = dest_dir / f"{os.getpid()}-{id(file)}-{safe_name}"
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File '{safe_name}' exceeds 100 MB limit")
    dest.write_bytes(content)
    return dest


def _safe_delete(path: Optional[Path]) -> None:
    try:
        if path and path.exists():
            path.unlink()
    except Exception:
        pass


# ─── POST /api/pid/upload ─────────────────────────────────────────────────────
@router.post(
    "/upload",
    response_model=UploadResult,
    summary="Upload and convert P&ID PDFs to images",
    description=(
        "Accepts two PDF files (markup_pdf, applied_pdf) and converts them to "
        "high-resolution PNG images. No AI analysis — pure conversion step."
    ),
)
async def upload_pid(
    markup_pdf:  UploadFile = File(..., description="P&ID PDF with handwritten markup"),
    applied_pdf: UploadFile = File(..., description="P&ID PDF with markups applied"),
) -> UploadResult:
    UPLOADS_DIR.mkdir(exist_ok=True)
    markup_path  = await _save_upload(markup_pdf,  UPLOADS_DIR)
    applied_path = await _save_upload(applied_pdf, UPLOADS_DIR)

    markup_temp = applied_temp = None
    try:
        markup_images,  markup_temp  = pdf_to_images(str(markup_path),  max_pages=5)
        applied_images, applied_temp = pdf_to_images(str(applied_path), max_pages=5)

        return UploadResult(
            markupPageCount  = len(markup_images),
            appliedPageCount = len(applied_images),
            message          = (
                f"Converted {len(markup_images)} markup page(s) and "
                f"{len(applied_images)} applied page(s) to PNG images successfully."
            ),
        )
    finally:
        _safe_delete(markup_path)
        _safe_delete(applied_path)
        if markup_temp:
            cleanup_temp_dir(markup_temp)
        if applied_temp:
            cleanup_temp_dir(applied_temp)


# ─── POST /api/pid/compare ────────────────────────────────────────────────────
@router.post(
    "/compare",
    response_model=ComparisonResult,
    summary="Compare markup P&ID against applied P&ID with Automated QC",
    description=(
        "Full pipeline: uploads two PDFs, converts pages to images, sends them to "
        "Ollama VLM for automated QC markup detection & verification, generates "
        "a compliance PDF report, and builds an annotated PDF highlighting unapplied markups."
    ),

)
async def compare_pid(
    markup_pdf:  UploadFile = File(..., description="PDF with handwritten or digital markup (Red=addition, Blue=comment, Green=deletion)"),
    applied_pdf: UploadFile = File(..., description="PDF with markups applied"),
    max_pages:   int        = Form(default=5, ge=1, le=HARD_PAGE_CAP,
                                   description="Max pages to analyse per PDF (default 5, max 10)"),
) -> ComparisonResult:
    UPLOADS_DIR.mkdir(exist_ok=True)

    markup_path  = await _save_upload(markup_pdf,  UPLOADS_DIR)
    applied_path = await _save_upload(applied_pdf, UPLOADS_DIR)

    log.info(
        "Starting P&ID comparison: markup=%s applied=%s max_pages=%d",
        markup_pdf.filename, applied_pdf.filename, max_pages,
    )

    markup_temp = applied_temp = None
    try:
        # Step 1: Convert PDFs to images
        markup_images,  markup_temp  = pdf_to_images(str(markup_path),  max_pages=max_pages)
        applied_images, applied_temp = pdf_to_images(str(applied_path), max_pages=max_pages)

        log.info(
            "Converted: markup=%d pages, applied=%d pages. Running AI analysis...",
            len(markup_images), len(applied_images),
        )

        # Step 2: AI vision analysis
        result = analyze_pid_markup(markup_images, applied_images)

        # Step 3: Generate PDF compliance report
        log.info("Generating PDF report for reportId=%s", result.reportId)
        report_bytes = generate_pdf_report(result)
        save_report(result.reportId, report_bytes)

        # Step 4: Generate visual annotated overlay PDF for unapplied markups
        log.info("Generating visual overlay PDF for unapplied markups reportId=%s", result.reportId)
        annotated_bytes = generate_annotated_overlay_pdf(applied_images, result.markups)
        if annotated_bytes:
            save_annotated_pdf(result.reportId, annotated_bytes)

        log.info(
            "Comparison complete — reportId=%s totalMarkups=%d unapplied=%d verdict=%s compliance=%.1f%%",
            result.reportId,
            result.summary.totalMarkups,
            result.summary.unapplied,
            result.summary.qcVerdict,
            result.summary.compliancePercentage,
        )
        return result

    except ValueError as exc:
        log.error("AI analysis failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        log.error("Unexpected error during comparison: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during P&ID analysis")
    finally:
        _safe_delete(markup_path)
        _safe_delete(applied_path)
        if markup_temp:
            cleanup_temp_dir(markup_temp)
        if applied_temp:
            cleanup_temp_dir(applied_temp)


# ─── GET /api/pid/report/{report_id} ─────────────────────────────────────────
@router.get(
    "/report/{report_id}",
    summary="Download P&ID comparison compliance report as PDF",
    description="Returns the generated A4 PDF compliance report for a given reportId.",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "PDF report binary"},
        404: {"model": ApiError},
    },
)
async def get_pid_report(report_id: str) -> Response:
    data = get_report(report_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail="Report not found. Reports are retained for the server session only.",
        )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="pid-report-{report_id[:8]}.pdf"',
            "Content-Length": str(len(data)),
        },
    )


# ─── GET /api/pid/annotated-pdf/{report_id} ──────────────────────────────────
@router.get(
    "/annotated-pdf/{report_id}",
    summary="Download visual annotated P&ID drawing PDF highlighting unapplied markups",
    description="Returns an annotated PDF of the P&ID drawing with visual callouts and target markers on remaining open/unapplied items.",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "Annotated PDF binary"},
        404: {"model": ApiError},
    },
)
async def get_annotated_pid_pdf(report_id: str) -> Response:
    data = get_annotated_pdf(report_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail="Annotated overlay PDF not found for this report ID.",
        )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="pid-annotated-{report_id[:8]}.pdf"',
            "Content-Length": str(len(data)),
        },
    )

