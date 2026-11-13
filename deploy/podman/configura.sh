#!/usr/bin/env bash
# Menu di configurazione del deploy Podman di mCorsi.
# Uso: sudo sh avvia.sh configura [comando]
set -eu

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)

APP_USER=mcorsi
APP_PORT=5100
IMAGE=localhost/mcorsi:latest
SECRET=mcorsi-tunnel-token
BACKUP_DIR=/var/backups/mcorsi
QUADLETS="mcorsi.pod mcorsi-data.volume mcorsi-env.volume mcorsi-web.container mcorsi-mcp.container"
USER_UNITS="mcorsi-backup.service mcorsi-backup.timer mcorsi-notifications.service mcorsi-notifications.timer"
SERVICES="mcorsi-pod.service mcorsi-web.service mcorsi-mcp.service mcorsi-tunnel.service"

ok() { printf 'OK: %s\n' "$*"; }
err() { printf 'ERRORE: %s\n' "$*" >&2; }

as_mcorsi() {
    (cd / && runuser -u "$APP_USER" -- env XDG_RUNTIME_DIR="/run/user/$(id -u "$APP_USER")" "$@")
}

user_systemctl() { systemctl --user -M "$APP_USER@" "$@"; }

app_home() { getent passwd "$APP_USER" | cut -d: -f6; }
quadlet_dir() { printf '%s/.config/containers/systemd\n' "$(app_home)"; }
unit_dir() { printf '%s/.config/systemd/user\n' "$(app_home)"; }

conferma() {
    local risposta
    printf '%s [s/N] ' "$1"
    read -r risposta || risposta=""
    case "$risposta" in
        s|S|si|SI|sì|Sì) return 0 ;;
        *) return 1 ;;
    esac
}

copia_come_mcorsi() {
    # copia_come_mcorsi <file_sorgente> <directory_destinazione>
    install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "$2"
    install -o "$APP_USER" -g "$APP_USER" -m 0644 "$1" "$2/"
}

crea_dir_utente() {
    local home
    home=$(app_home)
    install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "$home/.config"
    install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "$home/.config/containers"
    install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "$home/.config/systemd"
}

installa_tunnel_quadlet() {
    copia_come_mcorsi "$SCRIPT_DIR/mcorsi-tunnel.container" "$(quadlet_dir)"
}

utente_esiste() { id -u "$APP_USER" >/dev/null 2>&1; }

richiedi_utente() {
    if ! utente_esiste; then
        err "l'utente $APP_USER non esiste: esegui prima 'installa'."
        exit 1
    fi
}

# Estrae il token dall'ultima parola (accetta anche il comando completo
# "sudo cloudflared service install <token>") e lo valida.
# Scrive il token su stdout oppure esce con 1 senza output.
normalizza_token() {
    local raw=$1 last=""
    local parola
    for parola in $raw; do last=$parola; done
    if [[ "$last" =~ ^[A-Za-z0-9+/=_-]{40,}$ ]]; then
        printf '%s\n' "$last"
        return 0
    fi
    return 1
}

cmd_installa() {
    if ! utente_esiste; then
        useradd --system --create-home --shell /sbin/nologin "$APP_USER"
        ok "creato l'utente di sistema $APP_USER"
    fi
    if ! grep -q "^$APP_USER:" /etc/subuid 2>/dev/null; then
        usermod --add-subuids 200000-265535 --add-subgids 200000-265535 "$APP_USER"
        ok "assegnati subuid/subgid a $APP_USER"
    fi
    loginctl enable-linger mcorsi
    ok "avvio automatico al boot attivato (linger)"
    install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$BACKUP_DIR"
    ok "cartella backup: $BACKUP_DIR"

    printf 'Costruzione immagine (può richiedere alcuni minuti)...\n'
    # Rete dell'host: il DNS della rete di build di Podman può non risolvere i mirror.
    podman build --network=host -t "$IMAGE" -f "$REPO_ROOT/Containerfile" "$REPO_ROOT"
    podman save "$IMAGE" | as_mcorsi podman load
    ok "immagine $IMAGE disponibile per $APP_USER"

    crea_dir_utente
    local f
    for f in $QUADLETS; do
        copia_come_mcorsi "$SCRIPT_DIR/$f" "$(quadlet_dir)"
    done
    for f in $USER_UNITS; do
        copia_come_mcorsi "$SCRIPT_DIR/$f" "$(unit_dir)"
    done
    if as_mcorsi podman secret exists mcorsi-tunnel-token; then
        installa_tunnel_quadlet
        ok "tunnel Cloudflare già configurato: incluso"
    fi
    ok "file Quadlet e timer installati"

    user_systemctl daemon-reload
    user_systemctl restart mcorsi-pod.service
    user_systemctl enable --now mcorsi-backup.timer mcorsi-notifications.timer
    ok "applicazione avviata"
    printf '\nIndirizzo: http://%s:%s\n' "$(hostname -I 2>/dev/null | cut -d' ' -f1)" "$APP_PORT"
    printf 'Prossimi passi: firewall-on (accesso dalla rete), admin (primo amministratore), token (tunnel).\n'
}

cmd_token() {
    richiedi_utente
    local raw token
    printf 'Incolla il token del tunnel Cloudflare (non verrà mostrato): '
    read -rs raw || raw=""
    printf '\n'
    if ! token=$(normalizza_token "$raw"); then
        unset raw
        err "token non valido."
        exit 1
    fi
    unset raw
    printf '%s' "$token" | as_mcorsi podman secret create --replace mcorsi-tunnel-token - >/dev/null
    unset token
    ok "token salvato come secret Podman"
    installa_tunnel_quadlet
    user_systemctl daemon-reload
    user_systemctl restart mcorsi-tunnel.service
    ok "tunnel avviato"
}

cmd_tunnel_off() {
    richiedi_utente
    user_systemctl stop mcorsi-tunnel.service 2>/dev/null || true
    rm -f "$(quadlet_dir)/mcorsi-tunnel.container"
    if as_mcorsi podman secret exists "$SECRET"; then
        as_mcorsi podman secret rm "$SECRET" >/dev/null
    fi
    user_systemctl daemon-reload
    ok "tunnel disattivato e token rimosso"
}

cmd_autoavvio_on() {
    loginctl enable-linger mcorsi
    ok "avvio automatico attivato"
}

cmd_autoavvio_off() {
    printf "ATTENZIONE: L'applicazione si fermerà e non ripartirà al riavvio.\n"
    if ! conferma "Disattivare l'avvio automatico?"; then
        printf 'Annullato.\n'
        return 0
    fi
    loginctl disable-linger mcorsi
    ok "avvio automatico disattivato"
}

cmd_firewall_on() {
    firewall-cmd --permanent --add-port=5100/tcp >/dev/null
    firewall-cmd --reload >/dev/null
    ok "porta $APP_PORT/tcp aperta nella rete locale"
}

cmd_firewall_off() {
    firewall-cmd --permanent --remove-port=5100/tcp >/dev/null
    firewall-cmd --reload >/dev/null
    ok "porta $APP_PORT/tcp chiusa"
}

cmd_admin() {
    richiedi_utente
    as_mcorsi podman exec -it mcorsi-web flask --app wsgi admin bootstrap
    ok "procedura amministratore completata"
}

si_no() {
    if "$@" >/dev/null 2>&1; then printf 'sì'; else printf 'no'; fi
}

cmd_stato() {
    richiedi_utente
    local s
    for s in $SERVICES; do
        user_systemctl status "$s" --no-pager --lines=0 || true
        printf '\n'
    done
    as_mcorsi podman ps --pod || true
    printf '\nAvvio automatico (linger): %s\n' \
        "$(loginctl show-user "$APP_USER" --property=Linger --value 2>/dev/null || printf 'no')"
    printf 'Porta %s aperta nel firewall: %s\n' "$APP_PORT" "$(si_no firewall-cmd --query-port=5100/tcp)"
    printf 'Tunnel configurato: %s\n' "$(si_no as_mcorsi podman secret exists "$SECRET")"
    printf '\nUltime righe del registro:\n'
    journalctl CONTAINER_NAME=mcorsi-web -n 30 --no-pager || true
}

cmd_backup() {
    richiedi_utente
    user_systemctl start mcorsi-backup.service
    ok "backup eseguito in $BACKUP_DIR"
}

cmd_importa() {
    richiedi_utente
    local dir_instance=${1:-} file_env=${2:-}
    if [ -z "$dir_instance" ] || [ -z "$file_env" ]; then
        err "uso: configura importa <cartella_instance> <file_env>"
        exit 2
    fi
    if [ ! -d "$dir_instance" ]; then err "cartella non trovata: $dir_instance"; exit 1; fi
    if [ ! -f "$file_env" ]; then err "file non trovato: $file_env"; exit 1; fi
    if as_mcorsi podman run --rm -v mcorsi-env:/config "$IMAGE" test -e /config/.env; then
        err "Configurazione già presente: importazione annullata per non sovrascrivere le chiavi."
        exit 1
    fi

    user_systemctl stop mcorsi-pod.service || true
    local staging
    staging=$(mktemp -d)
    # shellcheck disable=SC2064
    trap "rm -rf '$staging'" RETURN
    cp -a "$dir_instance" "$staging/instance"
    install -m 0600 "$file_env" "$staging/env"
    chown -R "$APP_USER:$APP_USER" "$staging"
    as_mcorsi podman run --rm -v mcorsi-data:/data -v mcorsi-env:/config -v "$staging:/src:Z" "$IMAGE" \
        sh -c 'rm -rf /data/instance && mkdir -p /data/instance && cp -a /src/instance/. /data/instance/ && cp -a /src/env /config/.env'
    ok "dati e configurazione importati"
    user_systemctl start mcorsi-pod.service
    ok "applicazione riavviata"
}

cmd_disinstalla() {
    richiedi_utente
    if ! conferma "Fermare e rimuovere il servizio mCorsi (i dati restano)?"; then
        printf 'Annullato.\n'
        return 0
    fi
    user_systemctl disable --now mcorsi-backup.timer mcorsi-notifications.timer 2>/dev/null || true
    user_systemctl stop mcorsi-pod.service 2>/dev/null || true
    local f
    for f in $QUADLETS mcorsi-tunnel.container; do
        rm -f "$(quadlet_dir)/$f"
    done
    for f in $USER_UNITS; do
        rm -f "$(unit_dir)/$f"
    done
    user_systemctl daemon-reload || true
    loginctl disable-linger mcorsi
    ok "servizio rimosso. Dati, backup, token e utente sono stati conservati."
    cat <<EOF

Per cancellare anche i dati (irreversibile):
  sudo runuser -u $APP_USER -- env XDG_RUNTIME_DIR=/run/user/\$(id -u $APP_USER) podman volume rm mcorsi-data mcorsi-env
  sudo runuser -u $APP_USER -- env XDG_RUNTIME_DIR=/run/user/\$(id -u $APP_USER) podman secret rm $SECRET
  sudo rm -rf $BACKUP_DIR
  sudo userdel -r $APP_USER
EOF
}

esegui() {
    local comando=$1
    shift
    case "$comando" in
        installa) cmd_installa ;;
        token) cmd_token ;;
        tunnel-off) cmd_tunnel_off ;;
        autoavvio-on) cmd_autoavvio_on ;;
        autoavvio-off) cmd_autoavvio_off ;;
        firewall-on) cmd_firewall_on ;;
        firewall-off) cmd_firewall_off ;;
        admin) cmd_admin ;;
        stato) cmd_stato ;;
        backup) cmd_backup ;;
        importa) cmd_importa "$@" ;;
        disinstalla) cmd_disinstalla ;;
        *)
            err "comando sconosciuto: $comando"
            exit 2
            ;;
    esac
}

menu() {
    local scelta dir env
    while true; do
        cat <<'MENU'

mCorsi - configurazione Podman
  1) Installa o aggiorna
  2) Imposta il token del tunnel Cloudflare
  3) Disattiva il tunnel
  4) Attiva avvio automatico al boot
  5) Disattiva avvio automatico al boot
  6) Apri la porta 5100 nel firewall
  7) Chiudi la porta 5100 nel firewall
  8) Crea il primo amministratore
  9) Stato
 10) Backup ora
 11) Importa dati da un'installazione precedente
 12) Disinstalla
  0) Esci
MENU
        printf 'Scelta: '
        read -r scelta || return 0
        case "$scelta" in
            1) esegui installa ;;
            2) esegui token ;;
            3) esegui tunnel-off ;;
            4) esegui autoavvio-on ;;
            5) esegui autoavvio-off ;;
            6) esegui firewall-on ;;
            7) esegui firewall-off ;;
            8) esegui admin ;;
            9) esegui stato ;;
            10) esegui backup ;;
            11)
                printf 'Cartella instance: '; read -r dir
                printf 'File .env: '; read -r env
                esegui importa "$dir" "$env"
                ;;
            12) esegui disinstalla ;;
            0) return 0 ;;
            *) printf 'Scelta non valida.\n' ;;
        esac
    done
}

if [ "${1:-}" = "--solo-funzioni" ]; then
    return 0 2>/dev/null || exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
    printf 'Esegui con: sudo sh avvia.sh configura\n' >&2
    exit 1
fi

if [ "$#" -eq 0 ]; then
    menu
else
    esegui "$@"
fi
