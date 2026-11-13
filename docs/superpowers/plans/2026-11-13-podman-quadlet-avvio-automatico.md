# Avvio automatico Podman (Quadlet) + tunnel Cloudflare + menu configurazione — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dopo il riavvio della VM Fedora, mCorsi (web + MCP) e il client del tunnel Cloudflare ripartono da soli; tutto si configura da `sudo sh avvia.sh configura`.

**Architecture:** Immagine `localhost/mcorsi:latest` costruita da un `Containerfile`. Un pod Podman rootless `mcorsi` (utente di sistema `mcorsi` con linger) contiene tre container definiti come Quadlet (`mcorsi-web`, `mcorsi-mcp`, `mcorsi-tunnel`), generati da systemd come servizi utente con `Restart=always` e `WantedBy=default.target`. Il token del tunnel è un `podman secret`; `.env` e `instance/` vivono su volumi nominati; backup e notifiche girano tramite timer systemd utente che usano `podman exec`.

**Tech Stack:** Podman ≥ 5 + Quadlet, systemd (user manager + linger), firewalld, SELinux, Fedora 42 (Python 3.13), cloudflared, Bash, pytest.

**Spec:** nessun documento separato. I requisiti sono le richieste dell'utente:
- sessione del 10/11/2026: riavvio automatico al boot della VM; tunnel Cloudflare all'avvio con chiave configurabile; voce apposita nel menu del launcher;
- sessione del 13/11/2026: rootless con utente dedicato; porta raggiungibile **sia dalla LAN sia dal tunnel**.

## Global Constraints

- Server: Fedora con Podman. Nessun Docker e nessun `podman generate systemd` (deprecato): solo Quadlet.
- Rootless: utente di sistema `mcorsi`, `loginctl enable-linger mcorsi`, Quadlet in `/home/mcorsi/.config/containers/systemd/`.
- Porta web: `5100`, pubblicata sull'host (`PublishPort=5100:5100`) e aperta in firewalld (`5100/tcp`). Il Service URL di Cloudflare resta `http://localhost:5100`.
- MCP: `127.0.0.1:8001` dentro il pod, mai pubblicata sull'host.
- Il token del tunnel non va mai nel repo, nel DB, nei log, in `.env` o in un argomento della riga di comando: si legge con `read -rs` e si passa via stdin a `podman secret create --replace mcorsi-tunnel-token -`.
- Nel container: `.env` = `/config/.env` (volume `mcorsi-env`); instance = `/data/instance` (volume `mcorsi-data`); backup = `/backups` (bind `/var/backups/mcorsi:/backups:Z`).
- Il messaggio di commit termina con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Il lavoro si fa su un branch, non su `main`.
- Testi rivolti all'utente in italiano.
- Le installazioni Windows e bare-metal (`deploy/linux/`) restano funzionanti e non vanno modificate.

## Review Focus

1. **Token incollato insieme al comando.** L'utente incolla `sudo cloudflared service install eyJh...` invece del solo token. In quel caso si prende l'ultima parola. Se dopo questo il valore è vuoto o non rispetta `^[A-Za-z0-9+/=_-]{40,}$`, si rifiuta senza mostrarlo. *Test in Task 4.*
2. **Un `.env` presente nella directory di lavoro del container prevale su `MCORSI_ENV_FILE`.** Flask CLI carica il `.env` della cwd. `.containerignore` deve escludere `.env`, `instance/`, `.venv/` e `*.db`. *Test in Task 2.*
3. **`MCORSI_ENV_FILE` relativo o puntato a un symlink.** Deve dare un errore chiaro (exit 2), non creare file altrove. *Test in Task 1.*
4. **Avvio del tunnel senza secret.** Il container fallirebbe in loop. Per questo `configura.sh` installa `mcorsi-tunnel.container` solo dopo aver creato il secret e lo rimuove con "disattiva tunnel". *Test in Task 4.*
5. **Migrazione dall'installazione attuale avviata a mano con `podman run`.** I dati esistenti (`instance/` e `.env` con le chiavi di cifratura) vanno importati, non rigenerati. Chiavi nuove renderebbero illeggibili dati e backup cifrati. *Test in Task 4 (il comando importa rifiuta di sovrascrivere un `/config/.env` già presente); procedura in Task 5.*

---

### Task 1: `MCORSI_ENV_FILE` — `.env` in un percorso configurabile

**Files:**
- Modify: `mcorsi/startup_secrets.py` (aggiungere `resolve_env_path`; `_default_marker_path` e `main` la usano)
- Modify: `wsgi.py`, `mcp_server.py`
- Modify: `.env.example` (riga commentata `# MCORSI_ENV_FILE=/config/.env` con spiegazione)
- Test: `tests/test_startup_secrets.py`, `tests/test_launchers.py`

**Interfaces:**
- Produces: `resolve_env_path() -> Path` in `mcorsi/startup_secrets.py`.
  - Se `MCORSI_ENV_FILE` è impostata e non vuota, ritorna `Path(valore)`.
  - Altrimenti ritorna `DEFAULT_ENV_PATH`.
  - Se il percorso è relativo, solleva `StartupSecretError("MCORSI_ENV_FILE deve essere un percorso assoluto.")`.
- Produces: `main()` passa `env_path=resolve_env_path()` a `prepare_environment` e a `complete_environment`, e calcola il marker con `_default_marker_path(resolve_env_path())`.
- Produces: `wsgi.py` e `mcp_server.py` chiamano `load_dotenv(resolve_env_path())` prima di importare l'app.

- [ ] **Step 1: Scrivere i test che falliscono** (in `tests/test_startup_secrets.py`, riusare `startup_root` e `_clear_environment`)

```python
def test_resolve_env_path_defaults_to_project_env(monkeypatch):
    monkeypatch.delenv("MCORSI_ENV_FILE", raising=False)
    assert startup_secrets.resolve_env_path() == startup_secrets.DEFAULT_ENV_PATH

def test_resolve_env_path_honors_variable(monkeypatch, startup_root):
    target = startup_root / "config" / ".env"
    monkeypatch.setenv("MCORSI_ENV_FILE", str(target))
    assert startup_secrets.resolve_env_path() == target

def test_resolve_env_path_rejects_relative_path(monkeypatch):
    monkeypatch.setenv("MCORSI_ENV_FILE", "config/.env")
    with pytest.raises(startup_secrets.StartupSecretError, match="percorso assoluto"):
        startup_secrets.resolve_env_path()

def test_main_prepare_writes_env_file_from_variable(monkeypatch, startup_root):
    _clear_environment(monkeypatch)
    env_file = startup_root / "config" / ".env"
    env_file.parent.mkdir()
    monkeypatch.setenv("MCORSI_ENV_FILE", str(env_file))
    monkeypatch.setenv("MCORSI_INSTANCE_PATH", str(startup_root / "instance"))
    assert startup_secrets.main(["prepare"]) == 0
    assert "MCORSI_SECRET_KEY=" in env_file.read_text(encoding="utf-8")

def test_main_returns_2_for_relative_env_file(monkeypatch):
    monkeypatch.setenv("MCORSI_ENV_FILE", "relativo/.env")
    assert startup_secrets.main(["pending"]) == 2
```

In `tests/test_launchers.py`:

```python
def test_entrypoints_load_env_file_from_resolver():
    for relative_path in ("wsgi.py", "mcp_server.py"):
        text = _read(relative_path)
        assert "load_dotenv(resolve_env_path())" in text
        assert "load_dotenv()" not in text
```

- [ ] **Step 2: Verificare che falliscano**

Run: `pytest tests/test_startup_secrets.py tests/test_launchers.py -k "resolve_env_path or env_file" -v`
Expected: FAIL with `AttributeError: module 'mcorsi.startup_secrets' has no attribute 'resolve_env_path'`.

- [ ] **Step 3: Implementare `resolve_env_path` e aggiornare `main`, `wsgi.py` e `mcp_server.py`**

Nei due entrypoint: `from mcorsi.startup_secrets import resolve_env_path`. Il modulo non importa `mcorsi.config`, quindi va bene importarlo prima di `load_dotenv`. In `main` la chiamata va dentro il `try` esistente, così l'errore produce `ERRORE: ...` ed exit 2. Il controllo symlink già presente in `prepare_environment` (riga 162) copre anche il nuovo percorso.

- [ ] **Step 4: Eseguire tutta la suite**

Run: `pytest -q`
Expected: tutti i test PASS, inclusi quelli preesistenti di `test_startup_secrets.py`.

- [ ] **Step 5: Commit**

```bash
git add mcorsi/startup_secrets.py wsgi.py mcp_server.py .env.example tests/test_startup_secrets.py tests/test_launchers.py
git commit -m "Permetti di spostare il file .env con MCORSI_ENV_FILE"
```

---

### Task 2: Immagine container (`Containerfile` + `.containerignore`)

**Files:**
- Create: `Containerfile`, `.containerignore`
- Test: `tests/test_podman_deploy.py` (nuovo, stesso stile `_read` di `test_launchers.py`)

**Interfaces:**
- Produces: immagine `localhost/mcorsi:latest` con:
  - `WORKDIR /app`;
  - `ENV MCORSI_ENV_FILE=/config/.env MCORSI_INSTANCE_PATH=/data/instance MCORSI_BACKUP_PATH=/backups MCORSI_ENV=production`;
  - directory `/config`, `/data/instance` e `/backups` create nell'immagine (la copy-up del volume nominato le popola al primo uso);
  - nessun `ENTRYPOINT`: il comando lo decide il Quadlet.

- [ ] **Step 1: Scrivere i test che falliscono**

```python
def test_containerfile_builds_reproducible_runtime():
    text = _read("Containerfile")
    assert text.startswith("FROM registry.fedoraproject.org/fedora:42")
    assert "libreoffice-writer" in text
    assert "--require-hashes -r requirements.lock" in text
    for env in ("MCORSI_ENV_FILE=/config/.env", "MCORSI_INSTANCE_PATH=/data/instance",
                "MCORSI_BACKUP_PATH=/backups"):
        assert env in text
    assert "ENTRYPOINT" not in text

def test_containerignore_excludes_local_state_and_secrets():
    lines = _read(".containerignore").splitlines()
    for pattern in (".env", "instance/", ".venv/", "*.db", ".git/"):
        assert pattern in lines
```

- [ ] **Step 2: Verificare che falliscano**

Run: `pytest tests/test_podman_deploy.py -v`
Expected: FAIL with `FileNotFoundError` su `Containerfile`.

- [ ] **Step 3: Scrivere `Containerfile` e `.containerignore`**

- Pacchetti dnf: `python3 python3-pip libreoffice-writer liberation-fonts`, poi `dnf clean all`.
- Fedora 42 usa Python 3.13, la stessa versione usata per generare il lock.
- Ordine: prima `COPY requirements.lock`, poi `pip install --no-cache-dir --require-hashes -r requirements.lock`, infine `COPY . /app` (così si sfrutta la cache dei layer).
- `RUN chmod +x scripts/*.sh`.

- [ ] **Step 4: Verificare test e build reale**

Run: `pytest tests/test_podman_deploy.py -v` → PASS.
Sul server Fedora (o in qualsiasi host con podman):

```bash
podman build -t localhost/mcorsi:latest .
podman run --rm localhost/mcorsi:latest soffice --version
```

Expected: build OK; il secondo comando stampa `LibreOffice 2x.x...`. Se `pip` fallisce sugli hash per mancanza di wheel Linux, va rigenerato il lock seguendo `docs/RELEASE_CHECKLIST.md` e la cosa va segnalata, non aggirata.

- [ ] **Step 5: Commit**

```bash
git add Containerfile .containerignore tests/test_podman_deploy.py
git commit -m "Aggiungi l'immagine container per il deploy con Podman"
```

---

### Task 3: Quadlet del pod e timer utente

**Files:**
- Create: `deploy/podman/mcorsi.pod`
- Create: `deploy/podman/mcorsi-web.container`, `deploy/podman/mcorsi-mcp.container`, `deploy/podman/mcorsi-tunnel.container`
- Create: `deploy/podman/mcorsi-data.volume`, `deploy/podman/mcorsi-env.volume`
- Create: `deploy/podman/mcorsi-backup.service` + `.timer`, `deploy/podman/mcorsi-notifications.service` + `.timer` (unità utente)
- Test: `tests/test_podman_deploy.py`

**Interfaces:**
- Consumes: immagine `localhost/mcorsi:latest` (Task 2).
- Produces:
  - Nomi container: `ContainerName=mcorsi-web` / `mcorsi-mcp` / `mcorsi-tunnel`; `PodName=mcorsi`. Task 4 usa `podman exec mcorsi-web ...`.
  - Servizi generati: `mcorsi-pod.service`, `mcorsi-web.service`, `mcorsi-mcp.service`, `mcorsi-tunnel.service`.
  - Secret richiesto: `mcorsi-tunnel-token`.

Contenuto richiesto:

| File | Chiavi |
|---|---|
| `mcorsi.pod` | `PodName=mcorsi`, `PublishPort=5100:5100`, `[Install] WantedBy=default.target` |
| `mcorsi-web.container` | `Image=localhost/mcorsi:latest`, `Pod=mcorsi.pod`, `ContainerName=mcorsi-web`, `Exec=/app/scripts/run-production.sh 5100`, `Volume=mcorsi-data.volume:/data`, `Volume=mcorsi-env.volume:/config`, `Volume=/var/backups/mcorsi:/backups:Z`, `Environment=MCORSI_COOKIE_SECURE=false` (come `avvia.sh`), `HealthCmd=python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:5100/health/ready',timeout=3)"`, `HealthInterval=30s`, `Notify=healthy`, `[Service] Restart=always`, `TimeoutStartSec=300`, `[Install] WantedBy=default.target` |
| `mcorsi-mcp.container` | come web per immagine, pod e volumi `/data` e `/config` (niente `/backups`); `ContainerName=mcorsi-mcp`, `Exec=/app/scripts/run-mcp.sh`, `[Unit] After=mcorsi-web.service Requires=mcorsi-web.service`, `Restart=always`, `WantedBy=default.target` |
| `mcorsi-tunnel.container` | `Image=docker.io/cloudflare/cloudflared:<tag versione esplicito, mai latest>`, `Pod=mcorsi.pod`, `ContainerName=mcorsi-tunnel`, `Exec=tunnel --no-autoupdate run`, `Secret=mcorsi-tunnel-token,type=env,target=TUNNEL_TOKEN`, `After=`/`Requires=mcorsi-web.service`, `Restart=always`, `RestartSec=10`, `WantedBy=default.target` |
| `*.volume` | `VolumeName=mcorsi-data` / `mcorsi-env` |
| timer | uguali a `deploy/linux/` (02:00 e 08:00, `Persistent=true`, `RandomizedDelaySec=300`); i service usano `Type=oneshot` e `ExecStart=/usr/bin/podman exec mcorsi-web flask --app wsgi backup create` / `... notifications run` |

Per il tunnel: chiedere il tag stabile corrente su hub.docker.com/r/cloudflare/cloudflared/tags al momento dell'implementazione e scriverlo nel file.

- [ ] **Step 1: Scrivere i test che falliscono**

```python
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
    assert "podman exec mcorsi-web flask --app wsgi backup create" in _read(PODMAN + "mcorsi-backup.service")
    assert "podman exec mcorsi-web flask --app wsgi notifications run" in _read(PODMAN + "mcorsi-notifications.service")
    assert "OnCalendar=*-*-* 02:00:00" in _read(PODMAN + "mcorsi-backup.timer")
```

- [ ] **Step 2: Verificare che falliscano**

Run: `pytest tests/test_podman_deploy.py -v` → FAIL (`FileNotFoundError`).

- [ ] **Step 3: Scrivere i file secondo la tabella**

- [ ] **Step 4: Verificare i test e la sintassi Quadlet**

Run: `pytest tests/test_podman_deploy.py -v` → PASS.
Sul server, come `mcorsi`, dopo aver copiato i file:

```bash
/usr/libexec/podman/quadlet -dryrun -user
```

Expected: nessun errore; compaiono le unità `mcorsi-web.service` ecc.

- [ ] **Step 5: Commit**

```bash
git add deploy/podman tests/test_podman_deploy.py
git commit -m "Aggiungi i Quadlet Podman per avvio automatico e tunnel"
```

---

### Task 4: Menu `configura` nel launcher

**Files:**
- Create: `deploy/podman/configura.sh`
- Modify: `avvia.sh` (nuovo modo `configura`, da aggiungere anche al messaggio di usage)
- Test: `tests/test_podman_deploy.py`

**Interfaces:**
- Consumes: i file di Task 3; `ContainerName=mcorsi-web`; il secret `mcorsi-tunnel-token`.
- Produces: `deploy/podman/configura.sh [comando]`.
  - Senza argomenti mostra un menu numerato.
  - Con un argomento esegue direttamente il comando; il menu chiama le stesse funzioni.
  - Va eseguito come root: se `id -u` ≠ 0, stampa `Esegui con: sudo sh avvia.sh configura` ed esce con 1.

| Voce | Comando | Azione |
|---|---|---|
| 1 | `installa` | Crea l'utente di sistema `mcorsi` se manca (`useradd --system --create-home --shell /sbin/nologin`, più `usermod --add-subuids/--add-subgids` se non ha range in `/etc/subuid`). Esegue `loginctl enable-linger mcorsi`. Crea `/var/backups/mcorsi` (owner mcorsi, 0750). `podman build` come root dal repo, poi `podman save localhost/mcorsi:latest \| as_mcorsi podman load`. Copia i Quadlet (tunnel escluso) in `~mcorsi/.config/containers/systemd/` e i timer in `~mcorsi/.config/systemd/user/`. Poi `daemon-reload`, avvio di `mcorsi-pod.service`, `enable --now` dei due timer. Se il secret esiste già, copia anche `mcorsi-tunnel.container`. |
| 2 | `token` | Legge con `read -rs`; normalizza (ultima parola); valida con la regex della Review Focus. `printf '%s' "$token" \| as_mcorsi podman secret create --replace mcorsi-tunnel-token -`. Copia `mcorsi-tunnel.container`, `daemon-reload`, `restart mcorsi-tunnel.service`. |
| 3 | `tunnel-off` | `stop mcorsi-tunnel.service`, rimuove il file Quadlet, `podman secret rm mcorsi-tunnel-token`, `daemon-reload`. |
| 4 | `autoavvio-on` / `autoavvio-off` | `loginctl enable-linger` / `disable-linger mcorsi`. Prima di disattivare chiede conferma (`s/N`) e avvisa: "L'applicazione si fermerà e non ripartirà al riavvio." |
| 5 | `firewall-on` / `firewall-off` | `firewall-cmd --permanent --add-port=5100/tcp` / `--remove-port=5100/tcp`, poi `--reload`. |
| 6 | `admin` | `as_mcorsi podman exec -it mcorsi-web flask --app wsgi admin bootstrap` |
| 7 | `stato` | `systemctl --user -M mcorsi@ status` dei 4 servizi `--no-pager`, `podman ps --pod`, stato linger, porta aperta sì/no, tunnel configurato sì/no (solo esistenza del secret, mai il valore), ultime 30 righe di `journalctl --user -M mcorsi@ -u mcorsi-web.service`. |
| 8 | `backup` | `systemctl --user -M mcorsi@ start mcorsi-backup.service` |
| 9 | `importa <dir_instance> <file_env>` | Rifiuta se `mcorsi-env` contiene già `.env` (controllo con `podman volume mount`, oppure `podman run --rm` con `test -e`), con il messaggio "Configurazione già presente: importazione annullata per non sovrascrivere le chiavi." Altrimenti ferma il pod, copia in una staging di proprietà `mcorsi`, poi `podman run --rm -v mcorsi-data:/data -v mcorsi-env:/config -v staging:/src:Z localhost/mcorsi:latest` con `cp -a` verso `/data/instance` e `/config/.env`, e riavvia. |
| 10 | `disinstalla` | Chiede conferma. Ferma e rimuove i Quadlet e i timer, `daemon-reload`, `disable-linger`. **Non** rimuove volumi, `/var/backups/mcorsi`, secret, utente. Alla fine stampa i comandi manuali per cancellarli. |
| 0 | — | Esci |

Helper: `as_mcorsi() { runuser -u mcorsi -- env XDG_RUNTIME_DIR=/run/user/$(id -u mcorsi) "$@"; }`. Per systemd usare `systemctl --user -M mcorsi@`.

Regole dello script:
- `set -eu`;
- vietato `set -x`;
- il token non compare mai negli argomenti di un comando né in `echo`/`printf` verso stdout;
- ogni azione stampa un esito in italiano.

- [ ] **Step 1: Scrivere i test che falliscono**

```python
import shutil, subprocess, pytest

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
    assert 'echo "$token"' not in text and "service install" not in text.split("normalizza")[0]

def test_configura_enables_linger_and_opens_lan_port():
    text = _read(SCRIPT)
    assert "loginctl enable-linger mcorsi" in text
    assert "--add-port=5100/tcp" in text

def test_tunnel_quadlet_installed_only_with_secret():
    text = _read(SCRIPT)
    assert "podman secret exists mcorsi-tunnel-token" in text

def test_import_refuses_to_overwrite_existing_env():
    assert "per non sovrascrivere le chiavi" in _read(SCRIPT)

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash non disponibile")
def test_configura_is_valid_bash():
    subprocess.run(["bash", "-n", SCRIPT], check=True, cwd=PROJECT_ROOT)

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash non disponibile")
@pytest.mark.parametrize("raw, expected", [
    ("eyJh" + "A" * 60, "eyJh" + "A" * 60),
    ("sudo cloudflared service install eyJh" + "A" * 60, "eyJh" + "A" * 60),
    ("  eyJh" + "A" * 60 + "  ", "eyJh" + "A" * 60),
])
def test_normalizza_token_extracts_last_word(raw, expected):
    out = subprocess.run(["bash", "-c", f'. ./{SCRIPT} --solo-funzioni; normalizza_token "$1"', "_", raw],
                         capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert out.returncode == 0 and out.stdout.strip() == expected

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash non disponibile")
@pytest.mark.parametrize("raw", ["", "   ", "corto", "token con caratteri ;rm"])
def test_normalizza_token_rejects_invalid(raw):
    out = subprocess.run(["bash", "-c", f'. ./{SCRIPT} --solo-funzioni; normalizza_token "$1"', "_", raw],
                         capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert out.returncode != 0 and out.stdout == ""
```

`--solo-funzioni` permette di fare `source` dello script per definire le funzioni senza eseguire menu né controllo root. `normalizza_token(raw)` scrive su stdout il token valido, oppure esce con 1 senza output.

Nota: la riga `test_configura_never_exposes_tunnel_token` che usa `split("normalizza")` è fragile. In implementazione va semplificata a `assert 'echo "$token"' not in text` e `assert 'printf \'%s\\n\' "$token"' not in text`.

- [ ] **Step 2: Verificare che falliscano**

Run: `pytest tests/test_podman_deploy.py -v -k "configura or launcher or token or import"`
Expected: FAIL (`FileNotFoundError`, `"configura)" not in launcher`).

- [ ] **Step 3: Implementare `configura.sh` e il dispatch in `avvia.sh`**

In `avvia.sh` il ramo `configura)` va valutato **prima** della creazione della venv e fa `exec bash "$SCRIPT_DIR/deploy/podman/configura.sh" "$@"` (con gli argomenti rimanenti).

- [ ] **Step 4: Eseguire la suite**

Run: `pytest -q` → tutto PASS.
Se disponibile, anche `shellcheck deploy/podman/configura.sh` → nessun errore.

- [ ] **Step 5: Commit**

```bash
git add deploy/podman/configura.sh avvia.sh tests/test_podman_deploy.py
git commit -m "Aggiungi il menu configura per Podman, tunnel e firewall"
```

---

### Task 5: Documentazione e collaudo sul server Fedora

**Files:**
- Modify: `docs/DEPLOYMENT.md` (nuova sezione "Fedora + Podman (avvio automatico)" prima della sezione Cloudflare; la sezione Cloudflare rimanda al menu)
- Test: `tests/test_podman_deploy.py`

- [ ] **Step 1: Scrivere il test che fallisce**

```python
def test_deployment_doc_covers_podman_menu_and_migration():
    doc = _read("docs/DEPLOYMENT.md")
    for needle in ("sudo sh avvia.sh configura", "loginctl enable-linger mcorsi",
                   "firewall-cmd", "configura.sh importa", "podman secret"):
        assert needle in doc
```

- [ ] **Step 2: Verificare che fallisca** — `pytest tests/test_podman_deploy.py -k deployment_doc -v` → FAIL.

- [ ] **Step 3: Scrivere la sezione**

Contenuti:
- prerequisiti (`dnf install podman firewalld`);
- prima installazione (voce 1);
- token (voce 2: dove trovarlo nel pannello Cloudflare Zero Trust; Service URL invariato `http://localhost:5100`);
- firewall (voce 5);
- creazione admin (voce 6);
- verifica del riavvio (`sudo reboot`, poi voce 7);
- aggiornamento (`git pull` + voce 1);
- dove stanno i dati (volumi, `/var/backups/mcorsi`);
- SELinux (`:Z`);
- risoluzione problemi (`journalctl --user -M mcorsi@ -u mcorsi-web`).

Sottosezione **Migrazione dall'avvio manuale**:
1. Trovare i container attuali con `sudo podman ps -a` e `podman ps -a` dell'utente che li ha lanciati, e i loro mount con `podman inspect <nome> --format '{{json .Mounts}}'`.
2. Fermarli e impostare `--restart=no` (non rimuoverli finché il collaudo non è riuscito).
3. Eseguire `configura.sh installa`, poi `configura.sh importa <dir instance> <.env>`.
4. Fare il collaudo.
5. Solo dopo, `podman rm` dei vecchi container.
6. Togliere il vecchio `cloudflared` di sistema, se presente: `sudo systemctl disable --now cloudflared`. Altrimenti due connettori servirebbero lo stesso tunnel.

- [ ] **Step 4: Collaudo manuale sul server** (da riportare all'utente, nessun claim senza output)

```bash
sudo sh avvia.sh configura installa
sudo sh avvia.sh configura token        # incolla il token
sudo sh avvia.sh configura firewall-on
sudo reboot
# dopo il riavvio, senza fare login come mcorsi:
sudo sh avvia.sh configura stato
curl -fsS http://<ip-lan>:5100/health/ready
```

Expected:
- 4 servizi `active (running)`;
- `curl` dalla LAN risponde 200;
- l'URL pubblico Cloudflare risponde;
- il backup notturno compare in `/var/backups/mcorsi` il giorno dopo (oppure `configura backup` subito).

- [ ] **Step 5: Commit**

```bash
git add docs/DEPLOYMENT.md tests/test_podman_deploy.py
git commit -m "Documenta il deploy Fedora con Podman e la migrazione"
```
