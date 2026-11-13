# Audit di sicurezza — mCorsi

**Repository:** `C:\SV\mCorsi` · **Commit:** `b043690` (main) · **Data:** 29 agosto 2026
**Codice esaminato:** 6.363 righe del pacchetto `mcorsi/` + 498 righe legacy · **Copertura stimata:** ~95% dei sorgenti
**Tipo di analisi:** statica, in sola lettura. Nessun file dell'applicazione è stato modificato.

**Esito:** 25 vulnerabilità (3 critiche, 6 alte, 11 medie, 5 basse) + 3 bug funzionali + una lista di miglioramenti.

Le checkbox servono a tracciare le correzioni in un secondo momento.

---

## 1. Sintesi

Impianto complessivo solido: nessuna SQL injection, nessun XSS, nessuna primitiva pericolosa (`eval`, `pickle`, `shell=True`), schema relazionale ben vincolato, validazione WTForms coerente. I problemi si concentrano in tre punti: il rendering dei modelli DOCX, la coesistenza di un vecchio prototipo non autenticato, e il modo in cui i segreti e la modalità di esecuzione vengono scelti all'avvio.

### Registro dei rilievi

| ID | Gravità | Rilievo | Area | Fatto |
|---|---|---|---|---|
| V-01 | Critica | SSTI → esecuzione codice via modello DOCX | Attestati | [ ] |
| V-02 | Critica | Prototipo `app.py` senza autenticazione | Legacy | [ ] |
| V-03 | Critica | OTP partecipante aggira la password admin | Auth | [ ] |
| V-04 | Alta | Creazione account e invio mail non limitati | OTP | [ ] |
| V-05 | Alta | Aggancio a un'azienda senza prova | Portale | [ ] |
| V-06 | Alta | Rate limiting solo per IP | Auth | [ ] |
| V-07 | Alta | Derivazione debole della chiave Fernet | Crypto | [ ] |
| V-08 | Alta | Segreti di default nel percorso di avvio predefinito | Config | [ ] |
| V-09 | Alta | Servizi Windows registrati con privilegi elevati | Deploy | [ ] |
| V-10 | Media | Session fixation su due dei tre login | Auth | [ ] |
| V-11 | Media | Nessun header di sicurezza HTTP | Web | [ ] |
| V-12 | Media | Allowlist MIME con `application/octet-stream` | Upload | [ ] |
| V-13 | Media | Backup `.mcbackup` non cifrati | Backup | [ ] |
| V-14 | Media | Nessuna protezione sull'ultimo amministratore | Ruoli | [ ] |
| V-15 | Media | Fughe di informazioni nei messaggi d'errore | Web | [ ] |
| V-16 | Media | Server MCP: scope vuoti, allowlist vuote, PII estesa | MCP | [ ] |
| V-17 | Media | SMTP in chiaro e header non sanificati | Mail | [ ] |
| V-18 | Media | Import Excel: DoS in memoria ed errori mascherati | Import | [ ] |
| V-19 | Media | Lavoro bloccante dentro le richieste HTTP | Perf | [ ] |
| V-20 | Media | Migrazione automatica del database a ogni avvio | Deploy | [ ] |
| V-21 | Bassa | `/health/ready` pubblico espone le versioni | Web | [ ] |
| V-22 | Bassa | Policy password debole per lo staff | Auth | [ ] |
| V-23 | Bassa | Tentativi di questionario mai scaduti | Questionari | [ ] |
| V-24 | Bassa | Dipendenze senza lockfile, `pytest` in runtime | Supply chain | [ ] |
| V-25 | Bassa | Nessun `CheckConstraint` nello schema | Dati | [ ] |
| B-01 | Bug | `max_attempts` forzato a 3 in duplicazione e import | Questionari | [ ] |
| B-02 | Bug | Asimmetria di autorizzazione sulle ammissioni | Corsi | [ ] |
| B-03 | Bug | Import storico forza `attendance_status="attended"` | Import | [ ] |

---

## 2. Vulnerabilità critiche

Tre problemi da correggere prima di qualunque esposizione pubblica. I primi due permettono l'esecuzione di codice o l'accesso completo ai dati; il terzo permette di ottenere una sessione amministrativa senza conoscere la password.

### [ ] V-01 — Critica — Template injection nei modelli DOCX degli attestati

**Dove:** `mcorsi/services/certificates.py:70-88, 249`

Questa è la vulnerabilità più grave del progetto e va trattata come una possibile esecuzione di codice arbitrario sul server.

`inspect_template` valida un modello caricato confrontando le variabili con una allowlist:

```python
variables = set(DocxTemplate(str(path)).get_undeclared_template_variables())
unknown = sorted(variables - ALLOWED_PLACEHOLDERS)
```

`get_undeclared_template_variables()` restituisce solo i nomi *non dichiarati* nel template. Un payload Jinja2 che non introduce alcun nome nuovo — perché naviga attributi di oggetti già presenti nel contesto, oppure definisce le proprie variabili con `{% set %}` — attraversa il controllo senza produrre nessun elemento in `unknown`. Il rendering avviene poi in un ambiente Jinja2 **non sandboxato**:

```python
document.render(context, autoescape=True)
```

`autoescape=True` protegge dall'iniezione di markup nell'output, non dall'esecuzione dell'espressione. Da lì si raggiungono gli attributi interni degli oggetti Python del contesto e, per catena, l'esecuzione di comandi.

Il caricamento dei modelli è permesso a **qualsiasi utente con ruolo staff**: la conseguenza è un'escalation da operatore a compromissione completa del server, del database SQLite e di tutti i documenti privati. Su Windows il servizio gira con privilegi elevati (vedi V-09), quindi il codice eseguito è amministrativo.

**Correzione.** Rendere con un ambiente sandboxato, che blocca l'accesso agli attributi privati:

```python
from jinja2.sandbox import SandboxedEnvironment

jinja_env = SandboxedEnvironment(autoescape=True)
document.render(context, jinja_env)
```

In aggiunta: ispezionare l'AST del template (`jinja_env.parse()`) e rifiutare i nodi diversi da testo e output di variabili semplici, così da vietare del tutto `{% ... %}`; limitare il caricamento dei modelli al solo ruolo admin; registrare a audit ogni upload di modello.

### [ ] V-02 — Critica — Prototipo `app.py` nella radice: CRUD completo senza autenticazione

**Dove:** `app.py` (498 righe), `schema.sql`, `templates/`

Nella radice del repository sopravvive il prototipo iniziale: una seconda applicazione Flask, indipendente dal pacchetto `mcorsi/`, con CRUD completo su corsi, partecipanti e aziende e **nessun controllo di accesso**. Non ha login, non ha CSRF, non ha autorizzazioni. Definisce `SECRET_KEY = "dev-change-me"`, chiama `init_db()` alla costruzione e si avvia con `app.run(debug=True)`, cioè con la console di debug Werkzeug attiva — che è di per sé un canale di esecuzione di codice remoto.

Il file non viene servito dal deployment corrente, ma resta eseguibile con un singolo `python app.py` e verrà quasi certamente lanciato da qualcuno, prima o poi, sulla stessa macchina che contiene i dati reali.

**Correzione.** Eliminare `app.py`, `schema.sql` e la cartella `templates/` di radice. Se serve conservarli come riferimento storico, spostarli in `legacy/` e rimuovere il blocco `if __name__ == "__main__"`.

### [ ] V-03 — Critica — Il login OTP partecipante aggira l'autenticazione con password dello staff

**Dove:** `mcorsi/services/otp.py` · `mcorsi/portal/routes.py:55-70`

I due sistemi di autenticazione non sono separati per utente. `request_participant_code` accetta qualsiasi indirizzo email; se l'indirizzo corrisponde a un account esistente — **compreso un amministratore** — il codice viene inviato a quella casella. `verify_participant_code` aggiunge poi il ruolo `participant` all'utente e chiama `login_user()` sull'account originale, che conserva i suoi ruoli admin e operatore.

Il risultato è che una sessione amministrativa si ottiene con un codice a 6 cifre inviato per email, senza mai passare dalla password e senza mai incontrare il blocco per tentativi falliti che protegge il login staff. La sicurezza dell'intero pannello si riduce a quella della casella di posta dell'amministratore e alla robustezza del flusso OTP.

**Correzione.** Rifiutare la richiesta di OTP quando l'utente possiede un ruolo diverso da `participant`/`company`, restituendo comunque la stessa risposta generica per non rivelare l'esistenza dell'account:

```python
if user and user.has_role("admin", "operator"):
    return  # nessun codice inviato, risposta identica al caso "utente inesistente"
```

Non aggiungere mai il ruolo `participant` a un account che ne ha già altri: se un operatore deve anche frequentare corsi, usare un secondo account dedicato.

---

## 3. Gravità alta

Problemi sfruttabili da remoto o che indeboliscono in modo sistematico le difese, ma che richiedono condizioni aggiuntive o non portano da soli al controllo completo.

### [ ] V-04 — Alta — Creazione di account e invio di email non limitati

**Dove:** `mcorsi/services/otp.py` — `request_participant_code`

`request_participant_code` crea un nuovo `User` per qualunque email ricevuta, prima di applicare qualsiasi limite. I due tetti previsti non coprono il caso: quello per utente (5/ora) non può applicarsi alla prima richiesta di un indirizzo mai visto, e quello per IP (20/ora) viene saltato quando `remote_addr` è vuoto.

Ne derivano due abusi: riempimento illimitato della tabella utenti, e uso del server come amplificatore di posta verso destinatari arbitrari, con il dominio mittente reale — un ottimo modo per far finire il dominio in blacklist.

**Correzione.** Applicare un limite globale sulle richieste OTP prima di creare l'utente; trattare `remote_addr` vuoto come un IP a sé («unknown») invece di saltare il controllo; creare l'account solo alla *verifica* del codice, non alla richiesta. Considerare Flask-Limiter con storage persistente.

### [ ] V-05 — Alta — Un partecipante si aggancia a un'azienda esistente senza alcuna prova

**Dove:** `mcorsi/portal/routes.py` — `profile()` · `mcorsi/services/participants.py` · `mcorsi/participants/routes.py:43`

Dal profilo del portale un partecipante può indicare la partita IVA di un'azienda. Se l'azienda esiste già, l'utente vi viene collegato senza alcuna verifica: nessuna conferma da parte dell'azienda, nessun codice di invito. Un partecipante qualsiasi può così associarsi a un cliente esistente e comparire nei suoi elenchi.

La normalizzazione della P.IVA non aiuta a delimitare il rischio: `re.sub(r"[^A-Z0-9]", "", (value or "").upper())` non valida nulla, e `CompanyForm.vat_number` impone solo `Length(min=5, max=32)`, senza formato né checksum.

Sul lato azienda, l'accesso al portale è deciso da `company_required` in base al campo `verification_status`, che lo staff imposta liberamente dal form (`mcorsi/participants/routes.py:43`): un solo click errato apre l'accesso ai dati di un'azienda.

**Correzione.** Rendere l'associazione una *richiesta* in stato «pending», approvata da un referente aziendale o dallo staff. Validare la P.IVA italiana con il controllo di checksum a 11 cifre. Registrare a audit ogni cambio di `verification_status`.

### [ ] V-06 — Alta — Il rate limiting si basa solo sull'indirizzo IP

**Dove:** `mcorsi/auth/routes.py` · `mcorsi/config.py`

Il conteggio dei fallimenti di login usa `AuditLog` filtrato per IP: 10 tentativi in 15 minuti. Mancano tre elementi.

- Nessun blocco **per account**: distribuendo i tentativi su più IP si attacca una singola password senza mai incontrare un limite.
- I fallimenti **non vengono azzerati dopo un login riuscito**: l'utente legittimo continua a consumare la propria finestra.
- Con `ProxyFix(x_for=1)` e `TRUST_PROXY_HEADERS=True`, se l'applicazione resta raggiungibile direttamente (non solo tramite il tunnel Cloudflare) un attaccante controlla `X-Forwarded-For` e annulla ogni limite basato su IP.

Simmetricamente, dietro un NAT condiviso un solo utente maldestro blocca l'intero ufficio.

**Correzione.** Contare i fallimenti su `(account, IP)`, azzerarli al login riuscito, applicare un ritardo progressivo per account invece del blocco secco, e imporre a livello di firewall che il traffico arrivi solo dal tunnel.

### [ ] V-07 — Alta — Chiave Fernet derivata con un solo SHA-256 senza salt

**Dove:** `mcorsi/services/secrets.py`

```python
key = base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
```

La chiave che cifra le credenziali SMTP nasce da un singolo SHA-256 del segreto, senza salt e senza stiramento. Se il materiale di partenza è una passphrase (ed è il caso quando ricade su `SECRET_KEY`, vedi V-08), l'attacco a dizionario sul database sottratto è immediato: SHA-256 è progettato per essere veloce.

**Correzione.** Usare una KDF con costo — `Scrypt` o `PBKDF2HMAC` con salt persistito — oppure, meglio, esigere una chiave Fernet vera generata con `Fernet.generate_key()` e conservata in `MCORSI_ENCRYPTION_KEY`. Prevedere una procedura di rotazione con `MultiFernet`.

### [ ] V-08 — Alta — Il percorso di avvio predefinito gira con i segreti di sviluppo

**Dove:** `mcorsi/config.py:13-16` · `wsgi.py` · `avvia.cmd` · `avvia.sh`

Tutti i segreti collassano su uno solo quando non configurati:

```python
SECRET_KEY       = os.environ.get("MCORSI_SECRET_KEY", "development-only-change-me")
ENCRYPTION_KEY   = os.environ.get("MCORSI_ENCRYPTION_KEY", SECRET_KEY)
OTP_PEPPER       = os.environ.get("MCORSI_OTP_PEPPER", SECRET_KEY)
MCP_TOKEN_PEPPER = os.environ.get("MCORSI_MCP_TOKEN_PEPPER", SECRET_KEY)
```

Il controllo che blocca l'avvio con segreti di default esiste, ma scatta solo quando `config_name == "production"`. Gli script `run-production.*` e `run-mcp.*` impostano correttamente `MCORSI_ENV=production`. Il problema è il percorso documentato come «avvio rapido»: `wsgi.py` ricade su `"development"`, e i due lanciatori partono in modalità test —

```sh
mode=${1:-test}
if [ "$mode" = "produzione" ]; then export MCORSI_ENV=production
else export MCORSI_ENV=development; fi
host=${3:-${MCORSI_WEB_HOST:-0.0.0.0}}
```

— cioè `sh avvia.sh` senza argomenti mette in ascolto **0.0.0.0:5100** con la chiave `"development-only-change-me"`, senza flag `Secure` sui cookie e senza che nessun controllo sui segreti venga eseguito. Chi conosce il default può firmare cookie di sessione validi e decifrare le credenziali SMTP.

**Correzione.** Eseguire il controllo sui segreti in *ogni* modalità tranne `testing`. Far ricadere `wsgi.py` su `production` e richiedere l'esplicito `MCORSI_ENV=development` per la modalità permissiva. Far ascoltare la modalità di sviluppo su `127.0.0.1`. Rendere obbligatorio `flask admin generate-secrets` in fase di installazione — il comando già emette quattro segreti distinti.

### [ ] V-09 — Alta — Su Windows tutti i servizi girano con privilegi amministrativi

**Dove:** `deploy/windows/install-scheduled-tasks.ps1`

Le quattro attività pianificate — server web, server MCP, promemoria, backup — sono registrate con `-RunLevel Highest`:

```powershell
Register-ScheduledTask -TaskName "mCorsi Web" -Action $WebAction -Trigger $AtStartup `
    -User $User -RunLevel Highest -Force
```

Il server web è esposto (default `0.0.0.0`) e gira come amministratore, senza alcun equivalente dell'isolamento presente sul lato Linux. Qualsiasi esecuzione di codice nel processo — a partire da V-01 — diventa immediatamente controllo completo della macchina.

Il confronto con le unit systemd rende evidente il divario: lì ci sono utente dedicato, `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`, `ProtectHome=true` e `ReadWritePaths` ristretto.

**Correzione.** Creare un account di servizio locale senza privilegi, dargli i permessi solo sulle cartelle dati e backup, e registrare le attività con `-RunLevel Limited`. Riservare l'elevazione all'installazione.

---

## 4. Gravità media

Rafforzamenti attesi in un'applicazione che tratta dati personali e documenti aziendali. Nessuno di questi è sfruttabile da solo, ma ciascuno allarga la superficie o la portata di un altro problema.

### [ ] V-10 — Media — Session fixation: `session.clear()` presente in un login su tre

**Dove:** `mcorsi/portal/routes.py:61` (corretto) · `mcorsi/company_portal/routes.py:59` · `mcorsi/auth/routes.py:58`

Solo il portale partecipante azzera la sessione prima di `login_user()`. Il portale azienda e il login staff conservano la sessione anonima preesistente, quindi i dati che vi erano stati messi da un attaccante sopravvivono all'autenticazione.

**Correzione.** Aggiungere `session.clear()` prima di ogni `login_user()`, come già fatto in `portal.verify()`.

### [ ] V-11 — Media — Nessun header di sicurezza nelle risposte

**Dove:** `mcorsi/__init__.py`

L'applicazione non emette `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`/`frame-ancestors` né HSTS. Mancano anche il gestore di errore 500 (con Flask che, fuori da debug, mostra la pagina generica ma senza logging strutturato) e un `Permissions-Policy`.

**Correzione.** Aggiungere un `@app.after_request`:

```python
response.headers.setdefault("X-Content-Type-Options", "nosniff")
response.headers.setdefault("Referrer-Policy", "same-origin")
response.headers.setdefault("Content-Security-Policy",
    "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
if app.config["SESSION_COOKIE_SECURE"]:
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
```

Registrare inoltre un handler 500 che logga l'eccezione e mostra una pagina neutra.

### [ ] V-12 — Media — Allowlist MIME che accettano `application/octet-stream`

**Dove:** `mcorsi/documents/routes.py` · `mcorsi/imports/routes.py`

Le allowlist dei tipi accettati includono il jolly:

```python
allowed_mime_types={
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
}
```

`application/octet-stream` è ciò che il browser invia quando non riconosce il file, quindi la lista non filtra più nulla. Il tipo dichiarato dal client viene inoltre memorizzato e riproposto in download. Il rischio è contenuto da `as_attachment=True`, ma `nosniff` oggi manca (V-11).

In più, `CourseDocumentForm.file` è l'unico form di upload **senza** `FileAllowed`: gli altri cinque (modelli DOCX, firme PNG/JPG, attestati PDF, import XLSX, questionari JSON) lo dichiarano correttamente.

**Correzione.** Togliere il jolly e verificare il tipo reale dai magic bytes (`python-magic` o firma manuale). Normalizzare il MIME memorizzato a un valore derivato dall'estensione validata, non dall'header del client. Aggiungere `FileAllowed` a `CourseDocumentForm`.

### [ ] V-13 — Media — Gli archivi `.mcbackup` non sono cifrati

**Dove:** `mcorsi/services/backup.py`

Il backup è uno ZIP contenente il database completo e tutti i documenti privati: anagrafiche, attestati, allegati aziendali. Non è cifrato né protetto da password. Copiato su una condivisione di rete o un disco esterno, espone l'intero archivio dati con un doppio click.

**Correzione.** Cifrare l'archivio con una chiave dedicata (age, GPG, o Fernet su stream) e documentare dove custodire quella chiave, che **non** deve stare nello stesso backup.

### [ ] V-14 — Media — Nessuna protezione sull'ultimo amministratore

**Dove:** `mcorsi/settings/routes.py` — `staff_state`, `staff_password`

`staff_state` permette di disattivare qualunque account staff senza verificare che rimanga almeno un amministratore attivo: si può quindi restare chiusi fuori dal proprio pannello, recuperabile solo da CLI. `staff_password` consente inoltre a un admin di cambiare la password di un altro utente senza riautenticazione e senza notifica all'interessato.

**Correzione.** Rifiutare la disattivazione o la rimozione del ruolo quando è l'ultimo admin attivo. Richiedere la password corrente dell'operatore per il cambio password altrui e inviare una notifica all'utente interessato.

### [ ] V-15 — Media — Dettagli interni nei messaggi mostrati all'utente

**Dove:** `mcorsi/services/certificates.py:144` · `mcorsi/settings/routes.py` · `mcorsi/services/imports.py` · modello `EmailOutbox`

Quattro punti riportano all'interfaccia testo proveniente da componenti interni: lo stderr di LibreOffice (`f"Conversione PDF non riuscita: {detail[:300]}"`, che può contenere percorsi assoluti del filesystem), gli errori SMTP grezzi nei flash message, gli errori di parsing dell'import, e `EmailOutbox.last_error` che conserva il testo SMTP originale — potenzialmente con frammenti di credenziali o nomi host interni.

**Correzione.** Messaggio generico all'utente più identificativo dell'evento; dettaglio completo solo nel log applicativo lato server.

### [ ] V-16 — Media — Server MCP: scope vuoti, allowlist vuote, PII estesa

**Dove:** `mcorsi/mcp_server.py` · `mcorsi/services/mcp_tools.py`

- Alcuni tool sono registrati con `required_scopes=[]`: qualunque token valido li invoca, indipendentemente dai permessi assegnati.
- `enqueue_due_reminders` non passa da `record_tool_call`: l'azione che accoda email non lascia traccia nell'audit dei tool.
- Se `MCP_ALLOWED_HOSTS`/`MCP_ALLOWED_ORIGINS` restano vuote, le allowlist risultano vuote e la protezione anti DNS-rebinding perde efficacia.
- Le risposte contengono nomi ed email dei partecipanti e ragioni sociali: un token con scope di sola lettura esporta di fatto l'anagrafica verso un client LLM esterno.

**Correzione.** Assegnare uno scope esplicito a ogni tool, chiamare `record_tool_call` anche per i reminder, rifiutare l'avvio con allowlist vuote, e prevedere una modalità con dati pseudonimizzati per i tool che non richiedono l'identità.

### [ ] V-17 — Media — SMTP in chiaro possibile e header email non sanificati

**Dove:** `mcorsi/services/mail.py`

Se nella configurazione non sono attivi né SSL diretto né STARTTLS, le credenziali SMTP viaggiano in chiaro sulla rete: il form previene la combinazione contraddittoria dei due flag, ma non impone che almeno uno sia attivo. Inoltre `Subject` e `To` vengono composti senza rimuovere caratteri di fine riga, aprendo alla header injection se il valore proviene da dati controllabili dall'utente.

**Correzione.** Rendere obbligatorio SSL o STARTTLS salvo host `localhost`. Rimuovere `\r` e `\n` da ogni valore che finisce in un header, o costruire i messaggi con `email.message.EmailMessage`, che sanifica automaticamente.

### [ ] V-18 — Media — Import Excel: parsing in memoria ed eccezioni mascherate

**Dove:** `mcorsi/services/imports.py:69, 213-228, 297-300`

Il workbook viene aperto con `load_workbook(path, read_only=False, data_only=True)`: l'intero file finisce in memoria in forma espansa. Con il limite di upload a 20 MB, un XLSX compresso e pieno di celle può far esplodere la RAM del processo — un DoS a costo quasi nullo per chi ha un account staff.

Il gestore generico per riga nasconde inoltre un controllo di sicurezza:

```python
except Exception as exc:
    row.status = "error"
    row.warning = f"errore di importazione: {type(exc).__name__}"
```

Cattura anche `HistoricalImportError("L'email appartiene a un operatore e non può essere importata.")`, riducendo un rifiuto voluto a un generico errore di riga che l'operatore non può interpretare.

`_find_participant` esegue infine una scansione completa dei partecipanti con caricamento del profilo uno a uno (N+1) per ogni riga senza corrispondenza esatta di email.

**Correzione.** Usare `read_only=True` e limitare righe e colonne processate. Gestire `HistoricalImportError` in un ramo dedicato che ne propaga il messaggio. Sostituire la scansione con una query su cognome+nome e un `joinedload` del profilo. Rimuovere l'import inutilizzato di `Employment` (riga 15).

### [ ] V-19 — Media — Lavoro bloccante dentro le richieste HTTP

**Dove:** `mcorsi/settings/routes.py` — `run_notifications` · `mcorsi/services/mcp_access.py` — `verify_access_token`

`run_notifications` invia le email in modo sincrono dentro la richiesta: con una coda di qualche decina di messaggi e un server SMTP lento, il worker Waitress resta occupato fino al timeout del browser, e un errore a metà lascia la coda in stato parziale. `verify_access_token` esegue una `commit` a ogni chiamata MCP per aggiornare `last_used_at`, generando una scrittura SQLite per ogni richiesta di sola lettura.

**Correzione.** Far partire l'invio dal timer/scheduled task esistente e rendere il pulsante un semplice «accoda ed esegui in background». Aggiornare `last_used_at` in modo campionato (al massimo una volta al minuto per token).

### [ ] V-20 — Media — Migrazione automatica del database a ogni avvio

**Dove:** `scripts/run-production.sh` · `scripts/run-production.ps1`

Entrambi gli script eseguono `flask --app wsgi init-db` — cioè `alembic upgrade` — prima di avviare Waitress, a ogni riavvio del servizio. È una modifica di schema non presidiata, senza backup preventivo e senza percorso di rollback: un riavvio dopo un aggiornamento con una migrazione difettosa può corrompere l'unico database di produzione.

**Correzione.** Separare la migrazione dall'avvio: renderla un passo esplicito del deploy, preceduto dal backup e con un controllo di esito. In alternativa, mantenere l'automatismo ma eseguire prima `flask backup create` e interrompere l'avvio se il backup fallisce.

---

## 5. Gravità bassa

### [ ] V-21 — Bassa — `/health/ready` pubblico espone versioni e stato dei componenti

**Dove:** `mcorsi/main/routes.py`

L'endpoint non autenticato restituisce versione dell'applicazione, versione del database e stato per componente. Utile a un attaccante per correlare le versioni con vulnerabilità note.

**Correzione.** Rispondere pubblicamente solo `{"status":"ok"}` e riservare il dettaglio a chi è autenticato o a un token di monitoraggio.

### [ ] V-22 — Bassa — Policy password debole per gli account staff

**Dove:** `mcorsi/services/passwords.py`

Otto caratteri minimi, nessun limite massimo (una password molto lunga fa lavorare inutilmente l'hashing) e nessun controllo contro le password più diffuse. Sono gli account con i privilegi più alti del sistema.

**Correzione.** Portare il minimo a 12 caratteri, fissare un massimo a 128, e rifiutare le password presenti in una lista delle più comuni. Valutare l'MFA per il ruolo admin.

### [ ] V-23 — Bassa — Tentativi di questionario mai scaduti e avvio non serializzato

**Dove:** `mcorsi/questionnaires/routes.py`

Un tentativo aperto e mai inviato resta valido a tempo indefinito e non consuma il contatore `max_attempts`: il partecipante può aprire il questionario, leggere le domande, chiudere e ripresentarsi. L'avvio non è inoltre protetto da lock, quindi due richieste simultanee possono creare due tentativi.

**Correzione.** Far scadere i tentativi aperti dopo una finestra configurabile e conteggiarli comunque. Serializzare `/start` con un vincolo di unicità sul tentativo aperto per (questionario, partecipante).

### [ ] V-24 — Bassa — Dipendenze senza lockfile e `pytest` tra i requisiti runtime

**Dove:** `requirements.txt`

Le dipendenze sono dichiarate a intervalli, senza lockfile né hash: due installazioni a distanza di settimane producono ambienti diversi, e non c'è difesa contro una versione compromessa pubblicata a monte. `pytest` è installato anche in produzione; `reportlab` è dichiarato ma non risulta usato.

**Correzione.** Generare un `requirements.lock` con `pip-compile --generate-hashes`, separare i requisiti di sviluppo, rimuovere `reportlab` se confermato inutilizzato, e aggiungere `pip-audit` e `bandit` alla pipeline.

### [ ] V-25 — Bassa — Nessun `CheckConstraint` nello schema

**Dove:** `mcorsi/models.py`

Lo schema non contiene nemmeno un `CheckConstraint`. Tutte le colonne di stato — `status`, `attendance_status`, `verification_status`, `delivery_mode`, `response_type`, `source` — sono stringhe libere, validate solo dal codice applicativo. Qualunque percorso che aggiri i form (CLI, import, restore, script manuali) può scrivere uno stato che nessuna vista sa interpretare.

**Correzione.** Aggiungere `CheckConstraint` con i valori ammessi su ogni colonna di stato, in una migrazione dedicata; in alternativa passare a `Enum` nativi di SQLAlchemy.

---

## 6. Bug funzionali

Difetti non legati alla sicurezza, ma che producono comportamenti scorretti già oggi.

### [ ] B-01 — `max_attempts` forzato a 3 in duplicazione e import

**Dove:** `mcorsi/services/courses.py:141` · `mcorsi/services/questionnaire_transfer.py:153`

Entrambe le funzioni scrivono `max_attempts=3` come costante invece di riportare il valore dell'originale. Duplicare un corso o importare un questionario configurato con un numero diverso di tentativi ne perde silenziosamente l'impostazione — senza alcun avviso all'operatore.

**Correzione.** In `duplicate_course` copiare `source.max_attempts`; in `_build_questionnaire` leggere il campo dal payload, con default 3 e validazione di intervallo.

### [ ] B-02 — Asimmetria di autorizzazione sulle ammissioni

**Dove:** `mcorsi/courses/routes.py:166`

`_decide` applica `can_review_course` per verificare che l'operatore sia abilitato su quel corso; `add_admission`, che inserisce direttamente un'ammissione, non lo fa. Un operatore può quindi aggiungere partecipanti a corsi che non gli competono, pur non potendo decidere le richieste degli stessi corsi.

**Correzione.** Applicare `can_review_course(course)` anche in `add_admission`, come già in `_decide`.

**Nota.** Regola cambiata per decisione del committente il 13/11/2026: ogni operatore può iscrivere e decidere le richieste di qualsiasi corso. L'asimmetria non esiste più.

### [ ] B-03 — L'import storico marca tutti come «presenti»

**Dove:** `mcorsi/services/imports.py:290`

```python
enrollment = Enrollment(course=course, participant=participant, attendance_status="attended")
```

Ogni riga importata diventa una presenza confermata, senza che il file la dichiari. Poiché `attendance_status == "attended"` è una delle precondizioni di `readiness()` per generare l'attestato, un import di elenchi storici crea le condizioni per emettere attestati a persone che potrebbero non aver frequentato. È una scelta forse voluta per i corsi storici, ma non è dichiarata né configurabile.

**Correzione.** Rendere lo stato di presenza una scelta esplicita del form di import, con default conservativo, e mostrarlo nell'anteprima del batch.

---

## 7. Miglioramenti

Interventi di qualità e prestazioni, senza impatto diretto sulla sicurezza.

- [ ] **Query N+1 diffuse.** `enqueue_reminders` carica `Enrollment.query.all()` e naviga le relazioni una per una a ogni esecuzione pianificata. Stesso schema in `download_course_document`, `portal.dashboard`, `_course_choices`, nel ciclo di readiness di `courses.detail` e nei tool MCP di elenco. Risolvibile con `joinedload`/`selectinload` e con filtri sul database invece che in Python.
- [ ] **Codice duplicato.** `_masked_email` è ripetuto nei due portali: spostarlo in `services/`.
- [ ] **`set_attendance` ignora i valori non validi** invece di segnalarli: un errore di chiamata resta invisibile.
- [ ] **`normalize_email` non applica la normalizzazione Unicode.** Con `strip().casefold()` due indirizzi visivamente identici ma con composizioni Unicode diverse restano utenti distinti. Aggiungere `unicodedata.normalize("NFKC", …)`.
- [ ] **Manca un rate limiter generale** (Flask-Limiter) davanti agli endpoint di autenticazione e di richiesta OTP.
- [ ] **Pulizia del working tree.** Nove cartelle `pytest-cache-files-*` più `.pytest-tmp` sono presenti nell'albero di lavoro: aggiungerle a `.gitignore` e rimuoverle.
- [ ] **CI di sicurezza.** La suite di test è ampia (15 file, incluso `test_release_journey.py`); aggiungere `bandit` e `pip-audit` completa il quadro con un costo minimo.

---

## 8. Cosa è già fatto bene

Rilevato durante l'analisi e verificato sul codice: sono le parti da non toccare durante le correzioni.

- **Nessun XSS.** Zero occorrenze di `|safe`, `Markup` o autoescape disattivato in tutti i template; le email HTML passano da `html.escape()`.
- **Nessuna SQL injection.** Ogni query è ORM o `text()` costante senza interpolazione — anche nel vecchio `app.py`, che è comunque parametrizzato.
- **Nessuna primitiva pericolosa**: niente `eval`, `exec`, `pickle`, `os.system`, `shell=True`, `yaml.load`. `subprocess` è invocato in forma di lista.
- **Nessun IDOR** sui tentativi di questionario né sulle decisioni di ammissione (`admission.course_id != course.id` → 404); le risposte corrette non sono mai esposte al partecipante.
- **Schema relazionale accurato**: vincoli di unicità completi e semantiche `ondelete` corrette — `RESTRICT` per utenti e file, `CASCADE` per i figli, `SET NULL` per i riferimenti opzionali.
- **Validazione WTForms coerente**: `Length(max=…)` su ogni campo di testo, `Regexp` su OTP e codici corso, `FileAllowed` su cinque form di upload su sei, mutua esclusione SSL/STARTTLS.
- **Hardening systemd** sul lato Linux: utente dedicato, `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome`, `ReadWritePaths` ristretto, timer con `RandomizedDelaySec`.
- **Archiviazione file fuori dalla webroot** con chiavi UUID, guardia anti path traversal in `path_for`, guardia zip-slip nel restore e `send_file(as_attachment=True)`.
- **Uso corretto della crittografia applicativa**: `hmac.compare_digest` per OTP e token MCP, pepper separati per dominio, `secrets.choice` per i codici corso, `ssl.create_default_context()`.
- **CLI ben progettata**: password mai su argv, `admin bootstrap` idempotente e interattivo, `generate-secrets` che emette quattro segreti distinti, `backup restore` che richiede `--server-stopped`, token MCP mostrato una sola volta.
- **`questionnaire_transfer` è il percorso di input meglio validato**: limiti su domande e opzioni, controlli di tipo e intervallo, formato e schema fissati, import sempre come bozza non pubblicata.
- **Coda email robusta**: deduplica su `unique_key`, backoff esponenziale limitato, stato persistito.
- **`company_required` rivalida la sessione** contro le righe reali del database a ogni richiesta, incluso lo stato di verifica.
- **`scripts/smoke-test.ps1` verifica** che l'endpoint MCP risponda 401 senza token: un controllo di sicurezza vero dentro la suite.

---

## 9. Ordine di intervento consigliato

Le prime quattro voci sono poco invasive e coprono la maggior parte del rischio reale.

1. **Subito** — V-01 (`SandboxedEnvironment`, poche righe), V-02 (cancellazione file), V-03 (rifiuto OTP per account staff), V-08 (controllo segreti in ogni modalità, bind su `127.0.0.1` in sviluppo).
2. **Entro la prossima release** — V-04, V-05, V-06, V-07, V-09, più V-10 e V-11, che si risolvono con poche righe ciascuno.
3. **Pianificato** — V-12…V-20 e i tre bug funzionali, che richiedono migrazioni o revisione dei flussi.
4. **Manutenzione** — V-21…V-25 e la sezione miglioramenti.

---

## Note metodologiche

Analisi statica in sola lettura sul commit `b043690`. Nessuna verifica dinamica né test di exploit è stata eseguita: i rilievi V-01 e V-03 in particolare andrebbero confermati in un ambiente isolato prima e dopo la correzione. Copertura stimata ~95% dei sorgenti; non esaminati in dettaglio `migrations/` e la suite `tests/`.
