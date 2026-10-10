"""Analisi dei PDF non fidati in un processo separato con limiti di risorse."""

from __future__ import annotations

import subprocess  # nosec B404
import sys
from pathlib import Path

PDF_PROBE_TIMEOUT_SECONDS = 20
PDF_PROBE_MEMORY_BYTES = 512 * 1024 * 1024

# Eseguito con `python -I`: importa solo pypdf dall'ambiente virtuale e stampa il numero di pagine.
_PROBE_SCRIPT = (
    "import sys\n"
    "try:\n"
    "    import resource\n"
    "    _limit = int(sys.argv[2])\n"
    "    resource.setrlimit(resource.RLIMIT_AS, (_limit, _limit))\n"
    "except (ImportError, ValueError, OSError):\n"
    "    pass\n"
    "from pypdf import PdfReader\n"
    "print(len(PdfReader(sys.argv[1], strict=False).pages))\n"
)


class PdfProbeError(ValueError):
    pass


def count_pdf_pages(path: Path, *, timeout: float = PDF_PROBE_TIMEOUT_SECONDS) -> int:
    """Restituisce il numero di pagine o solleva PdfProbeError.

    Un PDF ostile può occupare CPU o memoria durante il parsing: il processo
    figlio viene terminato allo scadere del timeout e, su POSIX, non può
    superare il budget di memoria.
    """
    command = [sys.executable, "-I", "-c", _PROBE_SCRIPT, str(path), str(PDF_PROBE_MEMORY_BYTES)]
    try:
        completed = subprocess.run(  # nosec B603
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PdfProbeError("Analisi del PDF interrotta per timeout.") from exc
    except OSError as exc:
        raise PdfProbeError("Analisi del PDF non avviata.") from exc
    if completed.returncode != 0:
        raise PdfProbeError("Il file non contiene un PDF valido.")
    try:
        return int(completed.stdout.strip())
    except ValueError as exc:
        raise PdfProbeError("Il file non contiene un PDF valido.") from exc
