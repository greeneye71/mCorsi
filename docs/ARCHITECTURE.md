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

- `development`: SQLite, debug esplicito, cookie non Secure solo su localhost;
- `testing`: database isolato, email e storage finti;
- `production`: SQLite WAL sulla singola macchina iniziale, cookie Secure,
  proxy trusted e segreti da ambiente; PostgreSQL resta configurabile.

Con i volumi previsti non vengono introdotti Redis o code esterne. Email,
promemoria e generazione documenti useranno un outbox nel database e un worker
separato, eseguito sulla stessa macchina.

La configurazione sensibile non viene committata. La password SMTP sarà cifrata
con una chiave master fornita dall'ambiente di esecuzione.

## MCP

Il processo MCP riusa application factory, servizi e database ma non il server
WSGI. Espone Streamable HTTP stateless su localhost, dietro un hostname del
tunnel dedicato. I token sono casuali, conservati come HMAC, scadono, sono
revocabili e includono scope granulari. Ogni chiamata viene registrata; file,
password, OTP, credenziali SMTP e risposte corrette non sono esposti.

## Backup

Il modulo backup usa `sqlite3.Connection.backup()` per la copia consistente del
database e costruisce un archivio versionato con storage privato e manifest dei
checksum. Il ripristino è volutamente escluso dall'interfaccia web per ridurre
il rischio di sovrascritture accidentali.
