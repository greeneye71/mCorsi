from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_development_and_production_share_the_same_default_web_port():
    windows_launcher = _read("avvia.cmd")
    linux_launcher = _read("avvia.sh")
    powershell_production = _read("scripts/run-production.ps1")
    linux_production = _read("scripts/run-production.sh")
    environment_example = _read(".env.example")

    assert 'set "PORTA=5100"' in windows_launcher
    assert "${MCORSI_WEB_PORT:-5100}" in linux_launcher
    assert 'else { "5100" }' in powershell_production
    assert "${MCORSI_WEB_PORT:-5100}" in linux_production
    assert "MCORSI_WEB_PORT=5100" in environment_example

    combined = "\n".join(
        [
            windows_launcher,
            linux_launcher,
            powershell_production,
            linux_production,
            environment_example,
        ]
    )
    assert "MCORSI_TEST_PORT" not in combined
    assert "MCORSI_TEST_HOST" not in combined


def test_production_launchers_migrate_before_starting_waitress():
    for relative_path in ("scripts/run-production.sh", "scripts/run-production.ps1"):
        launcher = _read(relative_path)
        assert "flask --app wsgi init-db" in launcher
        assert launcher.index("flask --app wsgi init-db") < launcher.index("waitress")
