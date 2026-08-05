# mCorsi

Web application Flask, mobile-first, per amministrare corsi, partecipanti,
questionari e attestati. La versione corrente contiene l'architettura modulare,
l'accesso di amministratori/operatori, anagrafiche di partecipanti e aziende,
corsi e ammissioni, questionari, attestati PDF, importazione storico, portale
aziendale, notifiche, server MCP e backup verificabile con ripristino.

La specifica completa è in [docs/PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) e le
decisioni tecniche in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requisiti

- Python 3.11 o successivo;
- Windows per lo sviluppo oppure Linux/Windows per l'esercizio;
- LibreOffice headless per la generazione degli attestati;
- `cloudflared` per l'accesso esterno, senza esporre Flask
  direttamente su Internet.

## Avvio su Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m flask --app wsgi init-db
python -m flask --app wsgi admin create
python wsgi.py
```

Aprire `http://127.0.0.1:5000`. La password amministrativa viene richiesta in
modo interattivo e non compare negli argomenti né nella cronologia della shell.

Il nuovo database predefinito è `instance/mcorsi-v2.sqlite3`: il file del
prototipo precedente, se presente, non viene modificato.

## Funzioni disponibili

- creazione e modifica dei corsi da parte di tutti gli operatori;
- seduta singola con modello dati predisposto per più sedute;
- duplicazione in bozza con nuovo codice e senza partecipanti o risultati;
- anagrafiche partecipanti e storico dell'azienda di appartenenza;
- archivio aziende con partita IVA univoca e stato di verifica;
- richieste di ammissione, approvabili dal referente o dall'amministratore;
- registrazione automatica dell'iscrizione dopo l'approvazione;
- accesso partecipanti tramite OTP email a uso singolo;
- completamento autonomo del profilo e dell'azienda;
- configurazione SMTP amministrativa con password cifrata;
- builder per questionari a scelta singola o multipla;
- punteggi, soglia configurabile e massimo tre tentativi;
- blocco delle modifiche dopo il primo tentativo e snapshot degli esiti;
- documenti privati, modelli DOCX, firma immagine e attestati PDF immutabili;
- scadenze visibili a partecipanti e aziende;
- importazione dello storico da esportazioni XLSX di Microsoft Forms;
- outbox email e promemoria pianificabili;
- server MCP autenticato e limitato per assistenti degli operatori.

## Questionari

Gli operatori aggiungono uno o più questionari dalla pagina del corso. Ogni
domanda può avere fino a sei opzioni nella UI corrente e un punteggio distinto
per ciascuna risposta corretta. Prima della pubblicazione il sistema controlla
la presenza delle domande, delle risposte corrette e di un punteggio valido.

Nelle domande multiple vengono assegnati i punti delle opzioni corrette
selezionate; se viene selezionata anche un'opzione errata, la domanda vale zero.
Il partecipante non vede le soluzioni e può effettuare al massimo tre tentativi.

## Configurazione email e OTP

Dopo l'accesso come amministratore aprire **Impostazioni → Configurazione
email** e indicare server, porta, credenziali e mittente SMTP. Il pulsante
“Salva e invia prova” verifica immediatamente i parametri.

I codici hanno 6 cifre, durano 10 minuti, sono utilizzabili una sola volta e
vengono bloccati dopo 5 errori. Il database conserva soltanto un hash HMAC del
codice, mai il valore inviato via email.

Prima della produzione configurare quattro segreti lunghi e distinti:

```text
MCORSI_SECRET_KEY=...
MCORSI_ENCRYPTION_KEY=...
MCORSI_OTP_PEPPER=...
MCORSI_MCP_TOKEN_PEPPER=...
```

L'applicazione rifiuta l'avvio in produzione se le quattro chiavi non sono
configurate separatamente. Modificare `MCORSI_ENCRYPTION_KEY` dopo aver salvato
la password SMTP renderebbe necessario reinserire tale password.

## Comandi amministrativi

```powershell
python -m flask --app wsgi admin create
python -m flask --app wsgi admin create-operator
python -m flask --app wsgi admin set-password nome@example.it
python -m flask --app wsgi admin disable-user nome@example.it
python -m flask --app wsgi admin list-users
python -m flask --app wsgi mcp token-list
```

Le password devono contenere almeno 12 caratteri.

## Backup

Il backup contiene una copia consistente di SQLite, lo storage privato e un
manifest con checksum SHA-256. La destinazione deve idealmente essere un disco
o percorso sincronizzato distinto dalla macchina applicativa.

```powershell
python -m flask --app wsgi backup create
python -m flask --app wsgi backup list
python -m flask --app wsgi backup verify instance\backups\nome.mcbackup
python -m flask --app wsgi backup restore instance\backups\nome.mcbackup --server-stopped
```

Impostare `MCORSI_BACKUP_PATH` per cambiare destinazione. Il piano operativo
prevede un backup giornaliero automatico e una prova di ripristino trimestrale.
I launcher [scripts/backup.ps1](scripts/backup.ps1) e
[scripts/backup.sh](scripts/backup.sh) sono pronti rispettivamente per Utilità
di pianificazione di Windows e cron/systemd su Linux. Un orario iniziale
ragionevole è ogni notte alle 02:00.

## Test

```powershell
python -m pytest
python -m flask --app wsgi db check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1
```

## Produzione

In produzione i processi web e MCP ascoltano soltanto su localhost; Cloudflare
Tunnel inoltra il traffico HTTPS senza porte pubbliche in ingresso. La guida
completa per Waitress, systemd, Utilità di pianificazione, backup e tunnel è in
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
