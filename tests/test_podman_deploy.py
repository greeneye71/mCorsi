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
