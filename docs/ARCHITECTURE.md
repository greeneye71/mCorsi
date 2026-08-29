# Architettura iniziale

```text
Browser / dispositivi mobili
            |
      Cloudflare Tunnel
            |
        WSGI server
            |
         Flask UI
            |
  Servizi applicativi condivisi
      |        |         |
 SQLAlchemy  Storage   Outbox/worker
      |
 SQLite (iniziale) / PostgreSQL (opzionale)

Flask CLI ------------------^
Server MCP autenticato -----^
```

## Regole strutturali

- Le route validano input e autorizzazione, poi invocano servizi applicativi.
- I servizi contengono casi d'uso e transazioni; non dipendono dai template.
- I modelli descrivono persistenza e invarianti locali.
- File, email, OTP, PDF e provider futuri sono dietro interfacce sostituibili.
- Nessun blueprint accede a dati di un altro dominio aggirando il relativo
  servizio quando l'operazione modifica stato.
- Tutti gli identificativi pubblici sono UUID o codici casuali, non contatori.

## Package previsti

```text
mcorsi/
├── auth
├── users
├── participants
├── companies
├── courses
├── questionnaires
├── certificates
├── imports
├── notifications
├── settings
├── audit
├── services
├── templates
└── static
```

## Ambienti

- `development`: SQLite, debugger web disattivato e cookie non Secure per la
  rete di test fidata;
- `testing`: database isolato, email e storage finti;
- `production`: SQLite WAL sulla singola macchina iniziale, cookie Secure,
  proxy trusted e segreti da ambiente; PostgreSQL resta configurabile.

Con i volumi previsti non vengono introdotti Redis o code esterne. Email,
promemoria e generazione documenti useranno un outbox nel database e un worker
separato, eseguito sulla stessa macchina.

La configurazione sensibile non viene committata. La password SMTP sarà cifrata
con una chiave master fornita dall'ambiente di esecuzione.

## Versionamento e migrazioni

mCorsi usa tre informazioni complementari:

- versione applicativa semantica, attualmente `0.5.9`;
- versione intera dello schema, attualmente `6`, conservata nella riga unica
  della tabella `system_version`;
- revisione Alembic, che identifica esattamente l'ultima migrazione applicata.

Il comando `python -m flask --app wsgi version` riporta i tre valori. Le nuove
release che modificano lo schema devono incrementare `DATABASE_VERSION` e
includere una migrazione che aggiorni `system_version`. L'health check
`/health/ready` non dichiara pronta l'applicazione se lo schema è assente o
incompatibile, evitando di avviare codice nuovo su un database non aggiornato.

## MCP

Il processo MCP riusa application factory, servizi e database ma non il server
WSGI. Espone Streamable HTTP stateless su localhost, dietro un hostname del
tunnel dedicato. I token sono casuali, conservati come HMAC, scadono, sono
revocabili e includono scope granulari. Ogni chiamata viene registrata; file,
password, OTP, credenziali SMTP e risposte corrette non sono esposti.

## File privati

Lo storage assegna nomi fisici casuali e valida ogni nuovo file dopo la copia in
area privata. Il MIME memorizzato deriva dall'estensione consentita soltanto
dopo aver verificato il contenuto: parsing PDF, verifica Pillow per immagini e
struttura XML/ZIP per Office e OpenDocument. L'header MIME inviato dal client
non viene usato come fonte attendibile.

## Backup

Il modulo backup usa `sqlite3.Connection.backup()` per la copia consistente del
database e costruisce un archivio versionato con storage privato e manifest dei
checksum. Il contenitore viene poi cifrato a blocchi con AES-256-GCM, così da
autenticare anche backup di grandi dimensioni senza caricarli interamente in
memoria. Il ripristino è volutamente escluso dall'interfaccia web per ridurre il
rischio di sovrascritture accidentali.
