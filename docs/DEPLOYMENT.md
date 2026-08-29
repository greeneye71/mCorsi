# Installazione e gestione operativa

## Scelta consigliata

mCorsi ascolta per impostazione predefinita su `0.0.0.0:5100` tramite Waitress,
quindi è raggiungibile dalla rete locale. Un tunnel Cloudflare gestito da remoto
può continuare a pubblicare l'hostname HTTPS verso `http://localhost:5100`; non
occorre aprire porte in ingresso sul router. Il database SQLite e lo storage
devono risiedere su disco locale; i backup devono essere copiati su un secondo
disco o destinazione sincronizzata.

La porta web predefinita è 5100 sia per test/sviluppo sia per produzione; MCP
usa 8001. Indirizzo e porta web si modificano con gli argomenti dei launcher o
con `MCORSI_WEB_HOST` e `MCORSI_WEB_PORT`; `MCORSI_MCP_PORT` resta separata. Il
server MCP rimane vincolato a localhost.

## Preparazione comune

1. Installare Python 3.11+, LibreOffice e `cloudflared`.
2. Creare l'ambiente virtuale e installare `requirements.txt`.
3. Copiare `.env.example` in `.env` e generare i segreti con
   `python -m flask --app wsgi admin generate-secrets`.
4. Impostare percorsi assoluti per database, storage e backup.
5. Eseguire `python -m flask --app wsgi init-db` e creare l'amministratore.
6. Verificare `http://127.0.0.1:5100/health/ready` dopo l'avvio.

Esempio Linux per `/etc/mcorsi/mcorsi.env`:

```text
MCORSI_ENV=production
MCORSI_SECRET_KEY=...
MCORSI_ENCRYPTION_KEY=...
MCORSI_OTP_PEPPER=...
MCORSI_MCP_TOKEN_PEPPER=...
MCORSI_DATABASE_URL=sqlite:////var/lib/mcorsi/mcorsi.sqlite3
MCORSI_STORAGE_PATH=/var/lib/mcorsi/storage
MCORSI_BACKUP_PATH=/var/backups/mcorsi
MCORSI_LIBREOFFICE_PATH=/usr/bin/libreoffice
MCORSI_WEB_HOST=0.0.0.0
MCORSI_WEB_PORT=5100
MCORSI_MCP_PORT=8001
MCORSI_MCP_PUBLIC_URL=https://mcp.example.it/mcp
MCORSI_MCP_ALLOWED_HOSTS=mcp.example.it,127.0.0.1:8001,localhost:8001
```

## Linux con systemd

Copiare il progetto in `/opt/mcorsi`, creare l'utente di servizio `mcorsi` e le
directory `/var/lib/mcorsi`, `/var/backups/mcorsi`, `/etc/mcorsi`. Copiare le
unità da `deploy/linux` in `/etc/systemd/system`, quindi:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mcorsi.service
sudo systemctl enable --now mcorsi-mcp.service
sudo systemctl enable --now mcorsi-notifications.timer mcorsi-backup.timer
systemctl status mcorsi.service mcorsi-mcp.service
```

`mcorsi.service` usa `scripts/run-production.sh`, che esegue `flask init-db`
prima di avviare Waitress. Se una migrazione fallisce il server web non viene
messo in ascolto e systemd registra l'errore nel journal.

## Windows

Il comando manuale di produzione è:

```powershell
.\scripts\run-production.ps1
.\scripts\run-production.ps1 -ListenAddress "0.0.0.0:8080"
```

Da PowerShell avviato come amministratore si possono registrare web app,
server MCP, promemoria e backup nell'Utilità di pianificazione:

```powershell
.\deploy\windows\install-scheduled-tasks.ps1 -WebHost 0.0.0.0 -WebPort 5100 -McpPort 8001
```

Per una prova dal Prompt dei comandi, senza usare la porta Flask convenzionale
5000, eseguire `avvia.cmd test 5100`. Su Linux l'equivalente è
`sh avvia.sh test 5100`; `avvia.cmd produzione` e
`sh avvia.sh produzione` usano la stessa porta 5100.

## Accesso dalla rete locale

Dal computer server individuare l'indirizzo IPv4 con `ipconfig` su Windows o
`hostname -I` su Linux. Dagli altri dispositivi aprire, per esempio,
`http://192.168.1.20:5100`. Non usare letteralmente `0.0.0.0` nel browser: è
l'indirizzo di ascolto del server, non l'indirizzo del computer.

Su Windows può essere necessario creare una regola in ingresso, da PowerShell
avviato come amministratore:

```powershell
New-NetFirewallRule -DisplayName "mCorsi test 5100" -Direction Inbound `
  -Action Allow -Protocol TCP -LocalPort 5100 -Profile Private
```

Su Linux autorizzare la porta solo sulla rete privata usando il firewall della
distribuzione. L'accesso HTTP diretto è previsto per la modalità `test` e solo
su una rete fidata. In produzione i cookie sono marcati Secure: usare
l'hostname HTTPS di Cloudflare Tunnel o un reverse proxy TLS e non inoltrare le
porta 5100 sul router.

L'account selezionato deve avere il diritto di esecuzione all'avvio e accesso
ai percorsi configurati. Per un server non presidiato è preferibile Linux con
systemd o un account di servizio Windows dedicato.

## Cloudflare Tunnel

Cloudflare raccomanda un tunnel gestito da remoto. Nel pannello Cloudflare:

1. aprire **Networking → Tunnels**, creare il tunnel e scegliere il sistema;
2. aggiungere una route “Published application” per l'hostname desiderato;
3. usare come Service URL `http://localhost:5100` (o la porta web scelta);
4. per MCP aggiungere un secondo hostname, per esempio `mcp.example.it`, con
   Service URL `http://localhost:8001` (o la porta MCP scelta);
5. copiare il comando di installazione con token ed eseguirlo come
   amministratore/root:

```text
# Linux
sudo cloudflared service install <TUNNEL_TOKEN>

# Windows, Prompt dei comandi amministratore
cloudflared.exe service install <TUNNEL_TOKEN>
```

Il token consente di eseguire il tunnel: non va inserito nel repository né nei
log. In caso di esposizione deve essere ruotato dal pannello Cloudflare. Per lo
sviluppo temporaneo si può usare `cloudflared tunnel --url
http://localhost:5100`, ma i Quick Tunnel non sono adatti alla produzione.

Documentazione ufficiale aggiornata: [setup Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/setup/),
[token dei tunnel](https://developers.cloudflare.com/tunnel/advanced/tunnel-tokens/).

## Backup e ripristino

Il backup notturno produce un archivio `.mcbackup` verificato con SHA-256.
Conservare più versioni e provarne il ripristino almeno ogni tre mesi. Per
ripristinare:

1. fermare `mcorsi`, il timer notifiche e qualunque altro processo applicativo;
2. verificare l'archivio;
3. eseguire il ripristino con conferma esplicita;
4. applicare eventuali migrazioni e riavviare.

```bash
python -m flask --app wsgi backup verify /percorso/backup.mcbackup
python -m flask --app wsgi backup restore /percorso/backup.mcbackup --server-stopped
python -m flask --app wsgi db upgrade
python -m flask --app wsgi version
```

Prima della sostituzione il comando crea automaticamente un ulteriore backup
di sicurezza dello stato corrente. Dopo ogni creazione vengono conservati gli
ultimi `MCORSI_BACKUP_RETENTION_COUNT` archivi (30 per impostazione predefinita).

## Server MCP per ChatGPT e Claude

Il server MCP è un processo separato che ascolta solo su `127.0.0.1:8001` e
pubblica Streamable HTTP su `/mcp`. Avviarlo manualmente con:

```text
# Windows
.\scripts\run-mcp.ps1

# Linux
./scripts/run-mcp.sh
```

Creare un token con i soli permessi necessari; il valore viene mostrato una
sola volta:

```bash
python -m flask --app wsgi mcp token-create \
  --name "Claude operatori" \
  --creator-email admin@example.it \
  --scope courses:read --scope admissions:read --scope certificates:read
python -m flask --app wsgi mcp token-list
python -m flask --app wsgi mcp token-revoke PREFISSO
```

Per ChatGPT tramite API Responses usare l'URL HTTPS pubblico e il token come
header `Authorization: Bearer ...`. Claude API e Claude Code accettano lo stesso
endpoint remoto e Bearer token. Gli strumenti disponibili leggono corsi,
ammissioni, formazione, scadenze e coda email; `enqueue_due_reminders`, se
autorizzato con `automation:write`, accoda soltanto i messaggi e non li invia.

La connessione diretta come app personalizzata nell'interfaccia ChatGPT richiede
un flusso OAuth 2.1 completo. Questa release usa invece token statici revocabili
ed è quindi destinata all'uso server-to-server/API e Claude Code; OAuth resta
un'estensione futura. Riferimenti ufficiali: [server MCP OpenAI](https://developers.openai.com/plugins/build/mcp-server),
[autenticazione OpenAI](https://developers.openai.com/plugins/build/auth),
[MCP in Claude](https://docs.anthropic.com/en/docs/mcp).

## Aggiornamento

Creare un backup, fermare il servizio, aggiornare codice e dipendenze, quindi
riavviare. Gli script di produzione applicano automaticamente `flask init-db`
prima di Waitress; eseguire `flask version` per conferma. Controllare
`/health/ready`, la pagina degli operatori e la coda email. Non cambiare
`MCORSI_ENCRYPTION_KEY` senza
reinserire la password SMTP cifrata con la chiave precedente.

La release 0.5.3 richiede la versione database 4. La migrazione introduce la
verifica esplicita delle associazioni tra partecipanti e aziende, mantenendo
come verificate le associazioni già presenti. La precedente migrazione identifica i
corsi storici e aggiorna anche quelli già importati, consentendo l'emissione
degli attestati senza questionari pregressi. La tabella `system_version`
registra questa compatibilità, mentre `alembic_version` identifica la migrazione
esatta. Se i valori non sono allineati, `/health/ready` restituisce HTTP 503 e
il servizio deve restare fuori dal tunnel finché `flask db upgrade` non termina
correttamente.
