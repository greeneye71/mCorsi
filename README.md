# mCorsi

**Versione applicazione 0.5.13 · versione database 6**

Web application Flask, mobile-first, per amministrare corsi, partecipanti,
questionari e attestati. La versione corrente contiene l'architettura modulare,
l'accesso di amministratori/operatori, anagrafiche di partecipanti e aziende,
corsi e ammissioni, questionari, attestati PDF, importazione storico, portale
aziendale, notifiche, server MCP e backup verificabile con ripristino.

I corsi creati dall'importazione dello storico sono marcati come conclusi e
pregressi. Nell'anteprima l'operatore sceglie esplicitamente lo stato delle
presenze, inizialmente impostato su «Da confermare»; solo quelle confermate
possono ricevere l'attestato senza ricostruire i questionari, dopo avere
completato l'anagrafica e assegnato un modello DOCX.
Gli avvii di produzione Linux e Windows controllano e applicano le migrazioni
prima di mettere Waitress in ascolto. Se trovano la cifratura legacy, preservano
la vecchia chiave, generano in modo riservato le nuove chiavi Fernet, creano un
backup e ricifrano la password SMTP prima di rimuovere il fallback temporaneo.

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
python -m pip install --require-hashes -r requirements-dev.lock
Copy-Item .env.example .env
# Sostituire i cinque segreti di esempio con i valori generati dal comando dedicato.
python -m flask --app wsgi init-db
python -m flask --app wsgi admin create
python wsgi.py
```

Sul computer che esegue mCorsi aprire `http://127.0.0.1:5100`. La modalità di
test ascolta soltanto sull'interfaccia locale salvo richiesta esplicita. La
password amministrativa viene
richiesta in modo interattivo e non compare negli argomenti né nella cronologia
della shell.

Per una prova controllata dalla rete privata indicare esplicitamente `0.0.0.0`
e autorizzare la porta 5100 soltanto nel profilo **Privato** del firewall:

```cmd
avvia.cmd test 5100 0.0.0.0
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
`produzione` usa Waitress ma mantiene la stessa porta predefinita 5100.

Indirizzo e porta web sono unici per entrambe le modalità e possono essere
configurati con `MCORSI_WEB_HOST` e `MCORSI_WEB_PORT`. `MCORSI_MCP_PORT`
configura invece il processo MCP separato.

L'eventuale accesso diretto dalla LAN in modalità `test` usa HTTP non cifrato: va impiegato
soltanto su una rete privata fidata. La modalità `produzione` mantiene i cookie
Secure e deve essere raggiunta in HTTPS tramite Cloudflare Tunnel o un reverse
proxy TLS; non aprire la porta web sul router.

## Funzioni disponibili

- creazione e modifica dei corsi da parte di tutti gli operatori;
- riferimenti legislativi e programma trattato, riportabili negli attestati;
- seduta singola con modello dati predisposto per più sedute;
- duplicazione in bozza con nuovo codice e senza partecipanti o risultati;
- anagrafiche partecipanti e storico dell'azienda di appartenenza;
- archivio aziende con partita IVA univoca e stato di verifica;
- richieste di ammissione, approvabili dal referente o dall'amministratore;
- registrazione automatica dell'iscrizione dopo l'approvazione;
- accesso partecipanti tramite OTP email a uso singolo;
- pagina iniziale comune con accessi distinti per operatori, partecipanti e aziende;
- completamento autonomo del profilo e richiesta verificabile di associazione all'azienda;
- validazione dei file tramite contenuto reale e MIME normalizzato;
- configurazione SMTP amministrativa con password cifrata;
- versione applicazione e database visibile nella pagina di configurazione;
- nomi visualizzati per operatori e amministratori, distinti dalla mail di accesso;
- builder per questionari a scelta singola o multipla;
- archivio generale dei questionari con filtri, anteprima e duplicazione;
- esportazione JSON reimportabile ed esportazione Markdown leggibile;
- punteggi, soglia configurabile e massimo tre tentativi;
- blocco delle modifiche dopo il primo tentativo e snapshot degli esiti;
- documenti privati, modelli DOCX, firma immagine e attestati PDF immutabili;
- scadenze visibili a partecipanti e aziende;
- importazione dello storico da esportazioni XLSX di Microsoft Forms;
- outbox email e promemoria pianificabili;
- server MCP autenticato e limitato per assistenti degli operatori.

## Questionari

Gli operatori gestiscono tutti i questionari dal menu **Questionari**, oppure
dalla pagina del singolo corso. L'archivio consente di filtrare per corso e
stato, creare un questionario, visualizzarlo come apparirà al partecipante e
duplicarlo nello stesso corso o in un altro. Ogni domanda può avere fino a sei
opzioni nella UI corrente e un punteggio distinto per ciascuna risposta
corretta. Prima della pubblicazione il sistema controlla la presenza delle
domande, delle risposte corrette e di un punteggio valido.

Nelle domande multiple vengono assegnati i punti delle opzioni corrette
selezionate; se viene selezionata anche un'opzione errata, la domanda vale zero.
Il partecipante non vede le soluzioni e può effettuare al massimo tre tentativi.

Dal dettaglio sono disponibili due esportazioni:

- **JSON** è il formato ufficiale e versionato per trasferire o archiviare la
  definizione completa; può essere importato dal menu Questionari;
- **Markdown** è destinato a lettura, revisione e stampa e contiene anche
  soluzioni e punteggi, ma non viene importato.

I file non includono tentativi, risultati, identificativi interni o dati dei
partecipanti. Un questionario importato o duplicato è sempre una nuova bozza
indipendente e deve essere controllato prima della pubblicazione. Il limite di
caricamento del JSON è 1 MB; il formato corrente è `mcorsi.questionnaire`,
versione `1`.

## Attestati e contenuti del corso

Nella scheda del corso, oltre alla descrizione generale, sono disponibili i
campi **Riferimenti legislativi** e **Argomenti trattati**. Entrambi vengono
copiati quando si crea una nuova edizione e conservati nello snapshot
immutabile dell'attestato.

Il modello DOCX standard li riporta automaticamente. Nei modelli personalizzati
si possono inserire i segnaposto `{{ course_legal_references }}` e
`{{ course_topics }}`. I modelli caricati in precedenza restano immutati e
devono essere aggiornati e ricaricati se si desidera visualizzare i nuovi campi
nel PDF.

## Configurazione email e OTP

Dal menu principale aprire **Configurazione → Email SMTP** e indicare server,
porta, credenziali e mittente. Il pulsante
“Salva e invia prova” verifica immediatamente i parametri.

I codici hanno 6 cifre, durano 10 minuti, sono utilizzabili una sola volta e
vengono bloccati dopo 5 errori. Il database conserva soltanto un hash HMAC del
codice, mai il valore inviato via email.

Prima della produzione configurare cinque segreti lunghi e distinti:

```text
MCORSI_SECRET_KEY=...
MCORSI_ENCRYPTION_KEY=...
MCORSI_BACKUP_ENCRYPTION_KEY=...
MCORSI_OTP_PEPPER=...
MCORSI_MCP_TOKEN_PEPPER=...
```

L'applicazione rifiuta l'avvio in produzione se le cinque chiavi non sono
configurate separatamente e con almeno 32 caratteri. `MCORSI_ENCRYPTION_KEY`
deve inoltre essere una chiave Fernet valida; `python -m mcorsi.generate_secrets`
la genera nel formato corretto anche prima che l'applicazione sia configurata.
Per sostituirla senza perdere la password SMTP seguire la
procedura di rotazione descritta in `docs/DEPLOYMENT.md`.

## Comandi amministrativi

```powershell
python -m flask --app wsgi admin create
python -m flask --app wsgi admin create-operator
python -m flask --app wsgi admin set-password nome@example.it
python -m flask --app wsgi admin disable-user nome@example.it
python -m flask --app wsgi admin list-users
python -m flask --app wsgi admin generate-secrets
python -m flask --app wsgi admin rotate-encryption-key
python -m flask --app wsgi mcp token-list
python -m flask --app wsgi version
```

Le password devono contenere almeno 8 caratteri, una lettera maiuscola, una
minuscola, un numero e un carattere speciale.

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
manifest con checksum SHA-256, interamente protetti con cifratura autenticata
AES-256-GCM. La destinazione deve idealmente essere un disco o percorso
sincronizzato distinto dalla macchina applicativa. La chiave dedicata
`MCORSI_BACKUP_ENCRYPTION_KEY` va custodita separatamente e mai nella cartella
dei backup.

```powershell
python -m flask --app wsgi backup create
python -m flask --app wsgi backup list
python -m flask --app wsgi backup verify instance\backups\nome.mcbackup
python -m flask --app wsgi backup restore instance\backups\nome.mcbackup --server-stopped
python -m flask --app wsgi backup encrypt-legacy vecchio.mcbackup
```

Impostare `MCORSI_BACKUP_PATH` per cambiare destinazione. Il piano operativo
prevede un backup giornaliero automatico e una prova di ripristino trimestrale.
I launcher [scripts/backup.ps1](scripts/backup.ps1) e
[scripts/backup.sh](scripts/backup.sh) sono pronti rispettivamente per Utilità
di pianificazione di Windows e cron/systemd su Linux. Un orario iniziale
ragionevole è ogni notte alle 02:00.

## Test

`requirements.txt` e `requirements-dev.txt` dichiarano gli intervalli ammessi;
i file `.lock` fissano versioni e hash e sono gli unici usati per installazioni
e CI. `reportlab`, `pytest`, `pip-audit` e `bandit` sono presenti soltanto
nell'ambiente di sviluppo.

```powershell
python -m pytest
python -m pip_audit --strict --require-hashes -r requirements.lock
python -m bandit -q -r mcorsi mcp_server.py wsgi.py
python -m flask --app wsgi db check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1
```

## Produzione

In produzione il server web ascolta anche sulla rete locale, mentre MCP rimane
limitato a localhost. L'accesso autenticato di produzione richiede HTTPS;
Cloudflare Tunnel lo fornisce senza porte pubbliche in ingresso sul router. La
guida completa per Waitress, systemd, Utilità di pianificazione, backup e tunnel è in
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
