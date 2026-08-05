# mCorsi

**Versione applicazione 0.2.0 · versione database 1**

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

Dal normale Prompt dei comandi è sufficiente eseguire:

```cmd
avvia.cmd test
```

Lo script prepara automaticamente l'ambiente, applica le migrazioni e, solo
al primo avvio, richiede email e password dell'amministratore. L'ambiente di
test usa per impostazione predefinita la porta **5100**, così non entra in
conflitto con altre applicazioni Flask sulla porta 5000. La porta può essere
indicata come secondo argomento:

```cmd
avvia.cmd test 5200
avvia.cmd produzione 8080
```

In alternativa, la procedura manuale è:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m flask --app wsgi init-db
python -m flask --app wsgi admin create
python wsgi.py
```

Sul computer che esegue mCorsi aprire `http://127.0.0.1:5100`. Da un altro
dispositivo della stessa rete usare `http://IP-DEL-COMPUTER:5100`, sostituendo
l'indirizzo IPv4 mostrato da `ipconfig`. La password amministrativa viene
richiesta in modo interattivo e non compare negli argomenti né nella cronologia
della shell.

Il web server ascolta per impostazione predefinita su `0.0.0.0`, quindi su tutte
le interfacce di rete. Se Windows non mostra la richiesta automatica, occorre
autorizzare la porta 5100 nel profilo **Privato** del firewall. Per limitare
nuovamente l'accesso al solo computer locale usare:

```cmd
avvia.cmd test 5100 127.0.0.1
```

Il nuovo database predefinito è `instance/mcorsi-v2.sqlite3`: il file del
prototipo precedente, se presente, non viene modificato.

## Avvio su Linux

Dal terminale, nella cartella del progetto:

```bash
sh avvia.sh test
```

Lo script crea l'ambiente virtuale, installa le dipendenze, aggiorna il database
e richiede il primo amministratore. Per generare gli attestati occorre inoltre
installare LibreOffice; su Debian/Ubuntu, se manca il modulo per gli ambienti
virtuali, installare `python3-venv`. Anche qui la porta di test predefinita è
5100 e può essere cambiata, per esempio con `sh avvia.sh test 5200`. La modalità
`produzione` usa Waitress e la porta 8000, salvo diversa indicazione.

Indirizzi e porte predefiniti possono anche essere configurati come variabili
d'ambiente con `MCORSI_TEST_HOST`, `MCORSI_TEST_PORT`, `MCORSI_WEB_HOST`,
`MCORSI_WEB_PORT` e `MCORSI_MCP_PORT`.

L'accesso diretto dalla LAN in modalità `test` usa HTTP non cifrato: va impiegato
soltanto su una rete privata fidata. La modalità `produzione` mantiene i cookie
Secure e deve essere raggiunta in HTTPS tramite Cloudflare Tunnel o un reverse
proxy TLS; non aprire la porta web sul router.

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
- nomi visualizzati per operatori e amministratori, distinti dalla mail di accesso;
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

Dal menu principale aprire **Configurazione → Email SMTP** e indicare server,
porta, credenziali e mittente. Il pulsante
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
python -m flask --app wsgi version
```

Le password devono contenere almeno 12 caratteri.

## Versioni e migrazioni

La versione dell'applicazione è definita nel codice e mostrata discretamente
nella pagina di accesso. La versione numerica dello schema è memorizzata anche
nel database, nella tabella `system_version`; Alembic conserva inoltre la
revisione esatta delle migrazioni applicate. Il comando `flask version` mostra
tutti e tre i valori e segnala eventuali incompatibilità.

Ogni futura modifica allo schema deve includere una migrazione Alembic e
l'incremento di `DATABASE_VERSION`. L'endpoint `/health/ready` restituisce 503
se la versione del database non coincide con quella richiesta dal codice.

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

In produzione il server web ascolta anche sulla rete locale, mentre MCP rimane
limitato a localhost. L'accesso autenticato di produzione richiede HTTPS;
Cloudflare Tunnel lo fornisce senza porte pubbliche in ingresso sul router. La
guida completa per Waitress, systemd, Utilità di pianificazione, backup e tunnel è in
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
