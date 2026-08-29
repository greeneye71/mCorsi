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
    for relative_path in (
        "avvia.cmd",
        "avvia.sh",
        "scripts/run-production.sh",
        "scripts/run-production.ps1",
    ):
        launcher = _read(relative_path)
        assert "startup_secrets prepare" in launcher
        assert launcher.index("startup_secrets prepare") < launcher.index(
            "flask --app wsgi init-db"
        )
        assert "startup_secrets needs-backup" in launcher
        assert "flask --app wsgi backup create" in launcher
        assert launcher.index("flask --app wsgi backup create") < launcher.index(
            "flask --app wsgi init-db"
        )
        assert "flask --app wsgi init-db" in launcher
        assert launcher.index("flask --app wsgi init-db") < launcher.index("waitress")
        assert "flask --app wsgi admin rotate-encryption-key" in launcher
        assert launcher.index("flask --app wsgi init-db") < launcher.index(
            "flask --app wsgi admin rotate-encryption-key"
        )
        assert "startup_secrets complete" in launcher
        assert launcher.index("flask --app wsgi init-db") < launcher.index(
            "startup_secrets complete"
        )


def test_generic_launchers_fail_closed_and_development_is_local_by_default():
    windows_launcher = _read("avvia.cmd")
    linux_launcher = _read("avvia.sh")
    wsgi = _read("wsgi.py")

    assert 'set "MODALITA=produzione"' in windows_launcher
    assert "mode=${1:-produzione}" in linux_launcher
    assert "127.0.0.1" in windows_launcher
    assert "default_host=127.0.0.1" in linux_launcher
    assert 'os.environ.get("MCORSI_ENV", "production")' in wsgi


def test_direct_launchers_explicitly_support_trusted_lan_http():
    windows_launcher = _read("avvia.cmd")
    linux_launcher = _read("avvia.sh")

    for launcher in (windows_launcher, linux_launcher):
        assert "MCORSI_COOKIE_SECURE=false" in launcher
        assert "rete interna fidata" in launcher
        assert "MCORSI_COOKIE_SECURE=true" in launcher

    assert "MCORSI_COOKIE_SECURE=false" not in _read("scripts/run-production.sh")
    assert "MCORSI_COOKIE_SECURE=false" not in _read("scripts/run-production.ps1")
