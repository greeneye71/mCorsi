# Installazione e gestione operativa

## Scelta consigliata

mCorsi ascolta esclusivamente su `127.0.0.1:8000` tramite Waitress. Un tunnel
Cloudflare gestito da remoto pubblica l'hostname HTTPS verso
`http://localhost:8000`; non occorre aprire porte in ingresso sul router o sul
firewall. Il database SQLite e lo storage devono risiedere su disco locale; i
backup devono essere copiati su un secondo disco o destinazione sincronizzata.

## Preparazione comune

1. Installare Python 3.11+, LibreOffice e `cloudflared`.
2. Creare l'ambiente virtuale e installare `requirements.txt`.
3. Copiare `.env.example` in `.env` e generare i segreti con
   `python -m flask --app wsgi admin generate-secrets`.
4. Impostare percorsi assoluti per database, storage e backup.
5. Eseguire `python -m flask --app wsgi init-db` e creare l'amministratore.
6. Verificare `http://127.0.0.1:8000/health/ready` dopo l'avvio.

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

## Windows

Il comando manuale di produzione è:

```powershell
.\scripts\run-production.ps1
```

Da PowerShell avviato come amministratore si possono registrare web app,
server MCP, promemoria e backup nell'Utilità di pianificazione:

```powershell
.\deploy\windows\install-scheduled-tasks.ps1
```

L'account selezionato deve avere il diritto di esecuzione all'avvio e accesso
ai percorsi configurati. Per un server non presidiato è preferibile Linux con
systemd o un account di servizio Windows dedicato.

## Cloudflare Tunnel

Cloudflare raccomanda un tunnel gestito da remoto. Nel pannello Cloudflare:

1. aprire **Networking → Tunnels**, creare il tunnel e scegliere il sistema;
2. aggiungere una route “Published application” per l'hostname desiderato;
3. usare come Service URL `http://localhost:8000`;
4. per MCP aggiungere un secondo hostname, per esempio `mcp.example.it`, con
   Service URL `http://localhost:8001`;
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
http://localhost:8000`, ma i Quick Tunnel non sono adatti alla produzione.

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

Creare un backup, fermare il servizio, aggiornare codice e dipendenze, eseguire
`flask db upgrade`, quindi riavviare. Controllare `/health/ready`, la pagina
degli operatori e la coda email. Non cambiare `MCORSI_ENCRYPTION_KEY` senza
reinserire la password SMTP cifrata con la chiave precedente.
