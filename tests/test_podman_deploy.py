import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Percorso completo: su Windows "bash" nudo risolve prima lo stub WSL di System32.
BASH = shutil.which("bash")


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


PODMAN = "deploy/podman/"


def test_pod_publishes_web_port_only():
    pod = _read(PODMAN + "mcorsi.pod")
    assert "PublishPort=5100:5100" in pod
    assert "8001" not in pod


def test_all_containers_restart_and_start_at_boot():
    for name in ("mcorsi-web", "mcorsi-mcp", "mcorsi-tunnel"):
        text = _read(PODMAN + f"{name}.container")
        assert "Pod=mcorsi.pod" in text
        assert f"ContainerName={name}" in text
        assert "Restart=always" in text
        assert "WantedBy=default.target" in text


def test_web_container_is_health_checked_and_uses_volumes():
    web = _read(PODMAN + "mcorsi-web.container")
    assert "/health/ready" in web
    assert "Notify=healthy" in web
    assert "Volume=mcorsi-env.volume:/config" in web
    assert "Volume=/var/backups/mcorsi:/backups:Z" in web


def test_tunnel_reads_token_from_secret_and_pins_image():
    tunnel = _read(PODMAN + "mcorsi-tunnel.container")
    assert "Secret=mcorsi-tunnel-token,type=env,target=TUNNEL_TOKEN" in tunnel
    assert "cloudflared:latest" not in tunnel
    assert "Requires=mcorsi-web.service" in tunnel


def test_user_timers_run_inside_web_container():
    assert "podman exec mcorsi-web flask --app wsgi backup create" in _read(
        PODMAN + "mcorsi-backup.service"
    )
    assert "podman exec mcorsi-web flask --app wsgi notifications run" in _read(
        PODMAN + "mcorsi-notifications.service"
    )
    assert "OnCalendar=*-*-* 02:00:00" in _read(PODMAN + "mcorsi-backup.timer")


SCRIPT = "deploy/podman/configura.sh"


def test_launcher_dispatches_configura_mode():
    launcher = _read("avvia.sh")
    assert "configura)" in launcher
    assert "deploy/podman/configura.sh" in launcher


def test_configura_offers_every_command():
    text = _read(SCRIPT)
    for command in ("installa", "token", "tunnel-off", "autoavvio-on", "autoavvio-off",
                    "firewall-on", "firewall-off", "admin", "stato", "backup",
                    "importa", "disinstalla"):
        assert f"{command})" in text


def test_configura_never_exposes_tunnel_token():
    text = _read(SCRIPT)
    assert "read -rs" in text
    assert "podman secret create --replace mcorsi-tunnel-token -" in text
    assert "set -x" not in text
    assert 'echo "$token"' not in text
    assert "printf '%s\n' \"$token\"" not in text


def test_configura_enables_linger_and_opens_lan_port():
    text = _read(SCRIPT)
    assert "loginctl enable-linger mcorsi" in text
    assert "--add-port=5100/tcp" in text


def test_tunnel_quadlet_installed_only_with_secret():
    assert "podman secret exists mcorsi-tunnel-token" in _read(SCRIPT)


def test_import_refuses_to_overwrite_existing_env():
    assert "per non sovrascrivere le chiavi" in _read(SCRIPT)


@pytest.mark.skipif(BASH is None, reason="bash non disponibile")
def test_configura_is_valid_bash():
    subprocess.run([BASH, "-n", SCRIPT], check=True, cwd=PROJECT_ROOT)


def _normalizza(raw):
    return subprocess.run(
        [BASH, "-c", f'. ./{SCRIPT} --solo-funzioni; normalizza_token "$1"', "_", raw],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )


@pytest.mark.skipif(BASH is None, reason="bash non disponibile")
@pytest.mark.parametrize("raw, expected", [
    ("eyJh" + "A" * 60, "eyJh" + "A" * 60),
    ("sudo cloudflared service install eyJh" + "A" * 60, "eyJh" + "A" * 60),
    ("  eyJh" + "A" * 60 + "  ", "eyJh" + "A" * 60),
])
def test_normalizza_token_extracts_last_word(raw, expected):
    out = _normalizza(raw)
    assert out.returncode == 0 and out.stdout.strip() == expected


@pytest.mark.skipif(BASH is None, reason="bash non disponibile")
@pytest.mark.parametrize("raw", ["", "   ", "corto", "token con caratteri ;rm"])
def test_normalizza_token_rejects_invalid(raw):
    out = _normalizza(raw)
    assert out.returncode != 0 and out.stdout == ""


def test_deployment_doc_covers_podman_menu_and_migration():
    doc = _read("docs/DEPLOYMENT.md")
    for needle in ("sudo sh avvia.sh configura", "loginctl enable-linger mcorsi",
                   "firewall-cmd", "configura.sh importa", "podman secret"):
        assert needle in doc


def test_containerfile_pins_database_and_storage_inside_data_volume():
    text = _read("Containerfile")
    assert "MCORSI_DATABASE_URL=sqlite:////data/instance/mcorsi-v2.sqlite3" in text
    assert "MCORSI_STORAGE_PATH=/data/instance/storage" in text


def test_import_replaces_instance_instead_of_merging():
    assert "rm -rf /data/instance && mkdir -p /data/instance" in _read(SCRIPT)


def test_deployment_doc_requires_podman_5():
    doc = _read("docs/DEPLOYMENT.md")
    assert "Podman ≥ 5.0" in doc
    assert "Podman ≥ 4.4" not in doc
