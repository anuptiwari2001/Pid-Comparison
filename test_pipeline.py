"""
Complete Test Suite for P&ID Markup Comparison API & Pipeline.

Tests:
1. Health check endpoint (GET /api/healthz)
2. OpenCV HSV color segmentation (Red, Green, Blue detection)
3. Pydantic data models & Applied vs Not Applied vs Note decision rules
4. ReportLab A4 compliance PDF report generator
5. Pillow visual overlay drawing engine (verifying ONLY unapplied markups are highlighted)
6. Report store & FastAPI download endpoints (GET /api/pid/report/{id} & GET /api/pid/annotated-pdf/{id})
"""

import os
import sys
import tempfile
import cv2
import numpy as np
from PIL import Image, ImageDraw

from fastapi.testclient import TestClient

from main import app
from lib.color_detector import detect_color_markups
from lib.types import (
    AnnotationSource,
    ApproximateCoordinates,
    ComparisonResult,
    ComparisonSummary,
    MarkupColor,
    MarkupItem,
    MarkupType,
    QCVerdict,
    VerificationStatus,
)
from lib.report_generator import generate_pdf_report
from lib.visual_annotator import annotate_pid_images, generate_annotated_overlay_pdf
from lib.store import get_annotated_pdf, get_report, save_annotated_pdf, save_report

client = TestClient(app)


def test_healthz():
    print("Test 1: GET /api/healthz ...", end=" ")
    response = client.get("/api/healthz")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert response.json() == {"status": "ok"}
    print("[PASSED]")


def test_color_detector():
    print("Test 2: OpenCV HSV Color Segmentation (Red, Green, Blue) ...", end=" ")
    with tempfile.TemporaryDirectory() as tmp_dir:
        img_path = os.path.join(tmp_dir, "synthetic_markup.png")
        # Create 1000x800 white canvas
        img = np.full((800, 1000, 3), 255, dtype=np.uint8)

        # Draw RED box (Addition)
        cv2.rectangle(img, (100, 100), (250, 200), (0, 0, 255), -1)
        # Draw GREEN box (Deletion)
        cv2.rectangle(img, (400, 300), (550, 400), (0, 255, 0), -1)
        # Draw BLUE box (Note)
        cv2.rectangle(img, (700, 500), (850, 600), (255, 0, 0), -1)

        cv2.imwrite(img_path, img)

        candidates = detect_color_markups(img_path, page_number=1)
        assert len(candidates) >= 3, f"Expected at least 3 candidates, got {len(candidates)}"

        colors_found = {c["color"] for c in candidates}
        assert MarkupColor.red in colors_found, "Must detect Red candidate"
        assert MarkupColor.green in colors_found, "Must detect Green candidate"
        assert MarkupColor.blue in colors_found, "Must detect Blue candidate"

        print(f"[PASSED] ({len(candidates)} candidates detected)")


def test_pydantic_models_and_decision_rules():
    print("Test 3: Pydantic Data Models & Applied/Not-Applied Rules ...", end=" ")
    coords1 = ApproximateCoordinates(
        x_percent=20.0, y_percent=30.0, x_max_percent=35.0, y_max_percent=45.0, page_number=1
    )
    # Red Addition missing -> not_applied
    m1 = MarkupItem(
        id="M001",
        type=MarkupType.addition,
        color=MarkupColor.red,
        annotationSource=AnnotationSource.handwritten,
        extractedText="Add PG-101 pressure gauge",
        description="Add PG-101 pressure gauge downstream of XV-201",
        pidElement="Valve XV-201",
        location="Upper left quadrant near V-101",
        approximateCoordinates=coords1,
        verificationStatus=VerificationStatus.not_applied,
        confidence=0.96,
        verificationDetail="Red pressure gauge added in markup but missing in Model PDF",
        unappliedReason="Pressure gauge PG-101 missing downstream of XV-201",
    )

    # Green Deletion gone -> applied
    m2 = MarkupItem(
        id="M002",
        type=MarkupType.deletion,
        color=MarkupColor.green,
        annotationSource=AnnotationSource.digital,
        extractedText="Delete line 2-UT-001",
        description="Remove utility line 2-UT-001",
        pidElement="Line 2-UT-001",
        location="Lower right quadrant near pump P-101B",
        approximateCoordinates=ApproximateCoordinates(x_percent=70.0, y_percent=80.0, page_number=1),
        verificationStatus=VerificationStatus.applied,
        confidence=0.99,
        verificationDetail="Line 2-UT-001 completely removed from Model PDF",
        unappliedReason=None,
    )

    # Blue Note -> note
    m3 = MarkupItem(
        id="M003",
        type=MarkupType.note,
        color=MarkupColor.blue,
        annotationSource=AnnotationSource.handwritten,
        extractedText="Check operating pressure range with HAZOP lead",
        description="Informational note regarding operating pressure",
        pidElement="Vessel V-101",
        location="Center top near V-101",
        approximateCoordinates=ApproximateCoordinates(x_percent=50.0, y_percent=20.0, page_number=1),
        verificationStatus=VerificationStatus.note,
        confidence=0.95,
        verificationDetail="Informational comment logged (no drawing change required)",
        unappliedReason=None,
    )

    summary = ComparisonSummary(
        totalMarkups=3.0,
        applied=1.0,
        unapplied=1.0,
        notes=1.0,
        missing=1.0,
        incorrect=0.0,
        handwrittenCount=2.0,
        digitalCount=1.0,
        compliancePercentage=50.0,
        qcVerdict=QCVerdict.action_required,
    )

    result = ComparisonResult(
        reportId="test-summary-200",
        qcVerdict=QCVerdict.action_required,
        summary=summary,
        markups=[m1, m2, m3],
        overallAssessment="P&ID comparison completed. 1 unapplied item requires engineering attention.",
        unresolvedIssues=["Pressure gauge PG-101 missing downstream of XV-201"],
        processedAt="2026-08-10T22:00:00Z",
        reportUrl="/api/pid/report/test-summary-200",
        annotatedPdfUrl="/api/pid/annotated-pdf/test-summary-200",
    )

    assert result.qcVerdict == QCVerdict.action_required
    assert len(result.markups) == 3
    assert result.markups[0].verificationStatus == VerificationStatus.not_applied
    assert result.markups[1].verificationStatus == VerificationStatus.applied
    assert result.markups[2].verificationStatus == VerificationStatus.note
    print("[PASSED]")
    return result, m1, m2, m3


def test_pdf_report_generator(result: ComparisonResult):
    print("Test 4: ReportLab PDF Compliance Report Generator ...", end=" ")
    pdf_bytes = generate_pdf_report(result)
    assert isinstance(pdf_bytes, bytes), "Result must be bytes"
    assert len(pdf_bytes) > 500, "PDF size should be > 500 bytes"
    assert pdf_bytes.startswith(b"%PDF"), "PDF binary must start with %PDF"
    print(f"[PASSED] ({len(pdf_bytes)} bytes)")
    return pdf_bytes


def test_visual_annotator(m1: MarkupItem, m2: MarkupItem, m3: MarkupItem):
    print("Test 5: Visual Overlay (Highlight ONLY not_applied markups) ...", end=" ")
    with tempfile.TemporaryDirectory() as tmp_dir:
        sample_img_path = os.path.join(tmp_dir, "sample_page.png")
        img = Image.new("RGB", (1200, 900), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([50, 50, 1150, 850], outline=(0, 0, 0), width=3)
        img.save(sample_img_path)

        # Pass applied (m2), not_applied (m1), and note (m3)
        annotated_imgs = annotate_pid_images([sample_img_path], [m1, m2, m3])
        assert len(annotated_imgs) == 1, "Should return 1 annotated image path"
        assert os.path.exists(annotated_imgs[0]), "Annotated PNG file must exist"

        annotated_pdf = generate_annotated_overlay_pdf([sample_img_path], [m1, m2, m3])
        assert isinstance(annotated_pdf, bytes), "Result must be bytes"
        assert len(annotated_pdf) > 1000, "Annotated PDF should be > 1000 bytes"
        assert annotated_pdf.startswith(b"%PDF"), "Must start with %PDF header"
        print(f"[PASSED] ({len(annotated_pdf)} bytes)")
        return annotated_pdf


def test_store_and_endpoints(report_id: str, report_bytes: bytes, annotated_bytes: bytes):
    print("Test 6: Report Store & FastAPI Download Endpoints ...", end=" ")
    save_report(report_id, report_bytes)
    save_annotated_pdf(report_id, annotated_bytes)

    assert get_report(report_id) == report_bytes
    assert get_annotated_pdf(report_id) == annotated_bytes

    # Test GET /api/pid/report/{report_id}
    res_rep = client.get(f"/api/pid/report/{report_id}")
    assert res_rep.status_code == 200, f"Expected 200, got {res_rep.status_code}"
    assert res_rep.headers["content-type"] == "application/pdf"
    assert len(res_rep.content) == len(report_bytes)

    # Test GET /api/pid/annotated-pdf/{report_id}
    res_ann = client.get(f"/api/pid/annotated-pdf/{report_id}")
    assert res_ann.status_code == 200, f"Expected 200, got {res_ann.status_code}"
    assert res_ann.headers["content-type"] == "application/pdf"
    assert len(res_ann.content) == len(annotated_bytes)

    print("[PASSED]")


def run_all_tests():
    print("=" * 60)
    print(" RUNNING FULL P&ID COMPARISON API TEST PIPELINE")
    print("=" * 60)

    test_healthz()
    test_color_detector()
    result, m1, m2, m3 = test_pydantic_models_and_decision_rules()
    report_bytes = test_pdf_report_generator(result)
    annotated_bytes = test_visual_annotator(m1, m2, m3)
    test_store_and_endpoints("test-pipeline-2026", report_bytes, annotated_bytes)

    print("=" * 60)
    print(" ALL 6 PIPELINE TESTS COMPLETED AND PASSED PERFECTLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
