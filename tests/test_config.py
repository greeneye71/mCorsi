from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _production_cookie_flags(value: str | None) -> str:
    environment = os.environ.copy()
    if value is None:
        environment.pop("MCORSI_COOKIE_SECURE", None)
    else:
        environment["MCORSI_COOKIE_SECURE"] = value
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from mcorsi.config import ProductionConfig; "
                "print(ProductionConfig.SESSION_COOKIE_SECURE, "
                "ProductionConfig.REMEMBER_COOKIE_SECURE)"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_production_cookie_security_defaults_to_https():
    assert _production_cookie_flags(None) == "True True"


def test_production_cookie_security_can_be_disabled_explicitly_for_lan_http():
    assert _production_cookie_flags("false") == "False False"
