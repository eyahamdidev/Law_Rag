"""Text extraction and OCR.

Planned behavior:
- Read digital PDF text with pypdf or PyMuPDF.
- Send scanned pages to the local vision model through Ollama.
- Flag pages whose extraction is uncertain.
- Keep highlight coordinates so the web viewer can mark the passage.

The current function records that extraction did not run.
"""

from app.schemas.common import ModuleStatus, TraceStep


def inspect_document(filename: str, size_bytes: int) -> TraceStep:
    return TraceStep(
        module="intake.extract",
        status=ModuleStatus.placeholder,
        detail=(
            f"Received {filename} ({size_bytes} bytes). "
            "Text extraction and OCR are not connected yet."
        ),
    )
