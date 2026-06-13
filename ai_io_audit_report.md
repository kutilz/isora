# Audit Report: AI Input/Output System - AuralAI SDK

## 1. AI Architecture Overview

The AI system in this repository is divided into two main components:

- **Local AI (NPU):** Runs YOLOv11 (via `maix.nn`) for real-time object detection (e.g., person, car, etc.) in `device/core/ai_engine.py`.
- **Cloud AI (Vision):** Uses external model providers (OpenAI, Gemini, Claude) for more complex tasks like scene description and QRIS payment scanning.

## 2. Input Analysis (Prompt Construction & Injection)

### Prompt Construction

- **Location:** `device/config.py` and `device/config.json`.
- **Mechanism:** Prompts are defined as static strings editable via APIs and the Web Dashboard. There is no complex prompt engineering or dynamic context injection (like template engines) before requests are sent to adapters.
- **Findings:** Prompts are very basic. For example, the QRIS scanner prompt:
  
  > "Read this QRIS code. State the merchant name and amount if visible. Format: MERCHANT: [name], NOMINAL: [amount]. If it is not a QRIS code, answer: NOT QRIS."

### Prompt Injection Risk

- **Vulnerability:** High (Internal Network).
- **Details:** Since the `POST /ai-settings` endpoint in `device/server/web_server.py` did not originally enforce authentication, anyone on the same network could modify system prompts.
- **Impact:** An attacker could inject malicious instructions into system prompts to trick the AI into returning fraudulent or dangerous information to visually impaired users (e.g., falsifying QRIS transaction amounts or omitting hazards in scene descriptions).

## 3. Output Analysis (Parsing & Validation)

### Output Parsing

- **Mechanism:** No formal parsing is applied to AI outputs.
- **Location:** `device/core/ai_engine.py` inside the methods `trigger_scene_description` and `trigger_qris_scan`.
- **Findings:** The result from the AI Vision Adapter is immediately sent to the `AudioManager` to be announced as audio or written directly to logs (`qris_log.json`). The system blindly assumes the AI will always follow the requested output format (e.g., the `MERCHANT: ...` format).

### Output Validation

- **Findings:** There is no schema validation or sanity checking of the AI outputs.
- **Risiko (Risk):** If the AI produces unexpected outputs or hallucinations, the raw string is written directly to the logs and passed downstream.

## 4. AI Hallucination & Fallback Handling

### Hallucination Fallback

- **Mechanism:** No algorithmic hallucination detection is implemented.
- **Analysis:** The system relies entirely on the reliability of the vision models (GPT-4o, Gemini 1.5, etc.).
- **Audio Fallback (Unintentional):** Interestingly, the `AudioManager` only plays voice cues if a corresponding `.wav` file exists matching the text. Because AI scene descriptions are dynamic, they **will never be read aloud** unless a Text-to-Speech (TTS) engine is fully integrated or voice files are synthesized on-the-fly (not present in the core codebase).
- **Error Fallback:** Basic error handling exists for API failures (timeouts, invalid keys). The system plays generic error cues like `gagal_menganalisis` (failed to analyze) or `gagal_memindai` (failed to scan).

## 5. Main Components (Audit Files)

| Component | File | Audit Status |
|:---|:---|:---|
| **AI Engine** | `device/core/ai_engine.py` | Acts as the orchestrator between local NPU and cloud endpoints. Memory/resource release logic for loading and unloading models is well-handled. |
| **Adapters** | `device/adapters/*.py` | Clean implementation using `urllib.request`. Supports multiple providers with a consistent interface (`base.py`). |
| **Config** | `device/config.py` | Stores default prompts. Configuration storage/persistence requires hardening if used in untrusted environments. |
| **Scraper** | - | No external scrapers found; the system only captures frames from the internal camera stream. |

## 6. Recommendations

1. **Input Sanitization:** While prompts are internal, enforce character limits and filter out malicious control sequences on prompt inputs via the dashboard.
2. **Output Parsing (QRIS):** Use regular expressions or structured JSON parsing to extract fields from the AI's QRIS response. If parsing fails, retry or prompt the AI to correct the format (re-prompting).
3. **Authentication:** Enforce authentication (e.g., Token or Basic Auth) on the Web Dashboard to prevent unauthorized modification of prompts and API Keys.
4. **TTS Integration:** To read out dynamic scene descriptions, integrate a lightweight on-device TTS engine (like gTTS or an offline library suitable for MaixCAM) rather than relying on pre-recorded static `.wav` files.
5. **Hallucination Checking:** For QRIS payments, perform cross-checks with a local barcode/QR decoder library (performance permitting) as a secondary validation step.

---

*This report was automatically generated for the AuralAI-SDK repository audit.*
