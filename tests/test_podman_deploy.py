from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_containerfile_builds_reproducible_runtime():
    text = _read("Containerfile")
    assert text.startswith("FROM registry.fedoraproject.org/fedora:42")
    assert "libreoffice-writer" in text
    assert "--require-hashes -r requirements.lock" in text
    for env in (
        "MCORSI_ENV_FILE=/config/.env",
        "MCORSI_INSTANCE_PATH=/data/instance",
        "MCORSI_BACKUP_PATH=/backups",
    ):
        assert env in text
    assert "ENTRYPOINT" not in text


def test_containerignore_excludes_local_state_and_secrets():
    lines = _read(".containerignore").splitlines()
    for pattern in (".env", "instance/", ".venv/", "*.db", ".git/"):
        assert pattern in lines
