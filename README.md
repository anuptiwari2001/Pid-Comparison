# P&ID Markup Comparison API — Python / FastAPI

Vision-AI–powered REST API that reads P&ID documents, detects handwritten
colour-coded markup annotations, and verifies whether each one was correctly
applied in a revised document using Ollama VLM.

## Quick Start

### 1. System requirements

- **Poppler utils** (for PDF rendering):
  ```bash
  # Ubuntu / Debian
  sudo apt install poppler-utils

  # macOS
  brew install poppler
  ```
- **Ollama**:
  Download and install Ollama from [ollama.com](https://ollama.com).
  Pull the recommended vision model (`qwen3-vl:4b` or `qwen2.5-vl:3b`):
  ```bash
  ollama pull qwen3-vl:4b
  # OR: ollama pull qwen2.5-vl:3b
  ```

### 2. Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Environment variables

```bash
cp .env.example .env
# Edit .env to set OLLAMA_BASE_URL (default http://localhost:11434) and OLLAMA_MODEL (default qwen3-vl:4b)
```

### 4. Run the server

```bash
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt

uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

Interactive API docs are available at **http://localhost:8080/docs**

---

## Endpoints

|Method|Path|Description|
|-|-|-|
|`GET`|`/api/healthz`|Health check|
|`POST`|`/api/pid/upload`|Upload two PDFs → convert to images (no AI)|
|`POST`|`/api/pid/compare`|Full comparison + Automated QC + PDF report & Annotated overlay PDF|
|`GET`|`/api/pid/report/{reportId}`|Download A4 compliance PDF report|
|`GET`|`/api/pid/annotated-pdf/{reportId}`|Download P&ID drawing PDF with visual callouts for unapplied markups|

---

## POST /api/pid/compare

**Request:** `multipart/form-data`

|Field|Type|Required|Description|
|-|-|-|-|
|`markup_pdf`|file|✅|PDF with handwritten or computer-generated markups|
|`applied_pdf`|file|✅|Revised PDF where markups should be applied|
|`max_pages`|int|❌|Pages to analyse (default 5, max 10)|

**curl example:**

```bash
curl -X POST http://localhost:8080/api/pid/compare \
  -F "markup_pdf=@drawing_markup.pdf" \
  -F "applied_pdf=@drawing_applied.pdf" \
  -F "max_pages=5"
```

**Response JSON:**

```json
{
  "reportId": "550e8400-e29b-41d4-a716-446655440000",
  "qcVerdict": "action_required",
  "reportUrl": "/api/pid/report/550e8400-...",
  "annotatedPdfUrl": "/api/pid/annotated-pdf/550e8400-...",
  "summary": {
    "totalMarkups": 8,
    "applied": 6,
    "unapplied": 2,
    "missing": 1,
    "incorrect": 1,
    "handwrittenCount": 5,
    "digitalCount": 3,
    "compliancePercentage": 75.0,
    "qcVerdict": "action_required"
  },
  "markups": [
    {
      "id": "M001",
      "type": "addition",
      "color": "red",
      "annotationSource": "handwritten",
      "extractedText": "Add PG-101 downstream of XV-201",
      "description": "Add pressure gauge PG-101 downstream of valve XV-201",
      "pidElement": "Valve XV-201",
      "location": "Upper-left quadrant near vessel V-101",
      "approximateCoordinates": { "x_percent": 22, "y_percent": 15, "x_max_percent": 35, "y_max_percent": 25, "page_number": 1 },
      "verificationStatus": "not_applied",
      "confidence": 0.96,
      "verificationDetail": "PG-101 pressure gauge is missing from line 4-HC-1002 in Document 2",
      "unappliedReason": "Pressure gauge PG-101 not installed downstream of valve XV-201"
    }
  ],
  "overallAssessment": "Automated P&ID markup compliance review complete. 2 unapplied items require engineering action.",
  "unresolvedIssues": [
    "Pressure gauge PG-101 not installed downstream of valve XV-201"
  ],
  "processedAt": "2026-08-10T22:00:00Z"
}
```

**Download the Compliance PDF report & Visual Overlay PDF:**

```bash
# Download A4 Summary Report
curl http://localhost:8080/api/pid/report/550e8400-... -o report.pdf

# Download Visual Overlay Drawing PDF (Highlights remaining unapplied markups in red/amber)
curl http://localhost:8080/api/pid/annotated-pdf/550e8400-... -o drawing_annotated.pdf
```

---

## Markup Colour Standard

|Colour|Meaning|
|-|-|
|🔴 Red|Addition — add new element/connection|
|🔵 Blue|Comment/Note — informational|
|🟢 Green|Deletion — remove element/connection|

---

## File Structure

```
python_api/
├── main.py                 ← FastAPI app entry point
├── requirements.txt        ← Python dependencies
├── .env.example            ← Environment template
├── routes/
│   ├── health.py           ← GET /api/healthz
│   └── pid.py              ← P&ID upload / compare / report routes
└── lib/
    ├── types.py            ← Pydantic models (all API schemas)
    ├── pdf_converter.py    ← PDF → PNG via pdftoppm + Pillow resize
    ├── markup_analyzer.py  ← Ollama VLM vision analysis
    ├── report_generator.py ← ReportLab A4 PDF report builder
    └── store.py            ← In-memory report store
```

## TypeScript → Python equivalents

|TypeScript file|Python file|
|-|-|
|`src/lib/pid/types.ts`|`lib/types.py` (Pydantic models)|
|`src/lib/pid/pdf-converter.ts`|`lib/pdf_converter.py`|
|`src/lib/pid/markup-analyzer.ts`|`lib/markup_analyzer.py`|
|`src/lib/pid/report-generator.ts`|`lib/report_generator.py` (ReportLab)|
|`src/lib/pid/store.ts`|`lib/store.py`|
|`src/routes/pid/index.ts`|`routes/pid.py`|
|`src/routes/health.ts`|`routes/health.py`|
|`src/app.ts` + `src/index.ts`|`main.py`|

---

## Vision Models & System Specifications (4 GB Dedicated VRAM + 16 GB RAM)

This system is configured for local execution on machines with **4 GB dedicated VRAM** and **16 GB system RAM**.

### Recommended Models

| Model | Command | VRAM Usage | Features & Compatibility |
|---|---|---|---|
| **Qwen3-VL (4B) / Qwen2.5-VL (3B)** *(Recommended)* | `ollama pull qwen3-vl:4b`<br>*(or `ollama pull qwen2.5-vl:3b`)* | **~2.2 – 3.1 GB** | **Primary choice**. Fits entirely into 4GB VRAM. Superior OCR, handwriting recognition, and JSON output structured rendering. |
| **Moondream** *(Ultra-light)* | `ollama pull moondream` | **~1.7 GB** | **Ultra-fast & light**. Minimal memory footprint, ideal if running multiple background tasks simultaneously. |
| **LLaVA 7B / LLaVA-Phi3** | `ollama pull llava:7b` | **~2.9 – 3.8 GB** | Balanced vision model with strong general image understanding. |
| **Qwen2.5-VL 7B** *(High Precision)* | `ollama pull qwen2.5-vl:7b` | **~4.7 GB (Q4)** | Fits 4GB in GPU VRAM and seamlessly offloads ~1GB layer weights into 16GB CPU RAM via Ollama. |

To switch models, pull your desired model in Ollama and update `OLLAMA_MODEL` in `.env`:
```bash
# Example switching to moondream
ollama pull moondream
# In .env set: OLLAMA_MODEL=moondream
```

