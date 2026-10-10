# mCorsi — Report di analisi di bug e vulnerabilità

**Data:** 10 ottobre 2026  
**Repository:** `C:\SV\mCorsi`  
**Revisione:** `783dad5f1079968e19d3a2e501b20a2733f06773`  
**Versione applicazione:** 0.5.16; versione logica database: 6  
**Metodo:** revisione dei sorgenti, esecuzione dei test, audit delle dipendenze e riproduzioni su database isolati.

## 1. Esito e priorità

Sono emersi **17 rilievi: 7 di sicurezza e robustezza, 10 bug funzionali o operativi**. La classificazione complessiva è **5 alti, 9 medi e 3 bassi**. Non è stata confermata una vulnerabilità critica che consenta a un visitatore anonimo di ottenere direttamente privilegi amministrativi o eseguire codice sul server.

Le priorità sono la revoca effettiva di sessioni e token MCP, l'aggiornamento del parser PDF e l'affidabilità di backup e ripristino. Quindici rilievi sono stati riprodotti con prove locali, alcune mediante sincronizzazione dei thread o simulazione di errori. I restanti due sono documentati tramite versione vulnerabile e percorso di chiamata (S-06), oppure incompatibilità fra codice e configurazione systemd (B-07). Per questi ultimi non è stato eseguito un exploit PDF né un deployment Linux reale.

L'audit delle dipendenze ha restituito **23 avvisi su 57 pacchetti esaminati**, concentrati in PyJWT, pypdf e Werkzeug. Questi avvisi **non equivalgono a 23 vulnerabilità sfruttabili nell'applicazione**: occorre verificarne le condizioni e le API effettivamente usate.

La suite esistente passa anche usando l'ambiente con le versioni fissate dal progetto: **107 test superati, 1 avviso di deprecazione**. Bandit termina senza segnalazioni. Questi risultati non coprono i difetti di revoca, concorrenza e gestione degli errori descritti sotto.

| ID | Gravità | Rilievo | Evidenza |
|---|---|---|---|
| S-01 | Alta | Reset password e riattivazione non invalidano i cookie precedenti | Riprodotto via client HTTP |
| S-02 | Alta | Token MCP valido anche con titolare disabilitato | Riprodotto con chiamata MCP |
| S-03 | Media | Consumo e contatore degli OTP non atomici | Riprodotto con due thread sincronizzati |
| S-04 | Media | File orfani dopo rollback di un caricamento | Riprodotto via client HTTP |
| S-05 | Media | Promemoria con dati personali inviati anche ad aziende rifiutate | Riprodotto con outbox in memoria |
| S-06 | Alta | Parser PDF vulnerabile raggiungibile dagli upload | Lockfile, advisory e percorso di chiamata |
| S-07 | Bassa | Ragione sociale inserita senza escape nell'email HTML OTP | Riprodotto con outbox in memoria |
| B-01 | Media | Contatto aziendale principale disabilitato causa errore di unicità | Riprodotto nel servizio OTP |
| B-02 | Media | Account partecipante e referente aziendale indirizzato a una pagina 403 | Riprodotto via client HTTP |
| B-03 | Media | Due worker inviano due volte la stessa notifica | Riprodotto con due thread sincronizzati |
| B-04 | Media | Verifica backup accetta un archivio privo di database | Riprodotto su archivio di prova |
| B-05 | Bassa | Filtro MCP dei corsi futuri applicato dopo il limite | Riprodotto su dati sintetici |
| B-06 | Media | Un errore di flush blocca l'intera importazione storico | Riprodotto con errore di integrità simulato |
| B-07 | Alta | Percorsi di scrittura incompatibili con il deployment Linux | Analisi statica di codice e unità systemd |
| B-08 | Media | Ultimo tentativo aperto non riprendibile dalla dashboard | Riprodotto via client HTTP |
| B-09 | Alta | Errore nel cambio dello storage lascia il ripristino senza rollback | Riprodotto con errore filesystem simulato |
| B-10 | Bassa | Evento di creazione corso registra target `"None"` | Riprodotto su database di prova |

La gravità esprime l'impatto nel contesto di mCorsi, non un punteggio CVSS calcolato. In particolare S-06 è prioritario per l'accessibilità degli upload ai partecipanti e l'assenza di isolamento del parser; gli advisory citati classificano i singoli difetti della libreria come moderati.

## 2. Perimetro, metodo e limiti

Sono stati esaminati autenticazione staff, OTP partecipanti e aziende, autorizzazioni, anagrafiche, corsi e ammissioni, questionari, storage, modelli DOCX, generazione attestati, import XLSX, SMTP, notifiche, server MCP, backup, migrazioni, launcher e configurazioni di deployment. Sono stati letti anche i template HTML, i test e il workflow di sicurezza CI.

Le prove usano nuovi database SQLite e storage sotto `instance/audit-20261010/`. Non è stato aperto né modificato il database operativo; nessuna email reale è stata inviata. I client Flask e Starlette lavorano in-process, senza avviare un servizio pubblico. Le prove di errore filesystem e di integrità agiscono esclusivamente sui dati creati dallo script.

L'analisi non certifica la configurazione della macchina di produzione: firewall, tunnel, ACL Windows, permessi Linux, versione di LibreOffice, segreti effettivi e processi attivi non sono stati verificati. Non sono stati effettuati stress test, scansioni di rete, attacchi contro utenti reali o analisi della cronologia Git alla ricerca di credenziali.

Era già presente un report `AUDIT-SICUREZZA.md` datato 29 agosto 2026, riferito a una revisione precedente. È stato lasciato intatto. Le sue conclusioni non sono state importate automaticamente: varie criticità risultano corrette nel codice attuale, come documentato nella sezione 7.

### Controlli eseguiti

| Controllo | Esito |
|---|---|
| Suite con Python globale, versioni non identiche al lockfile | 107 passed in 54,76 s |
| Suite con `instance/lock-venv/Scripts/python.exe` | 107 passed, 1 warning in 52,56 s |
| Bandit sul pacchetto e sugli entry point | Exit code 0, nessun rilievo |
| pip-audit sul lockfile di produzione | Exit code 1: 23 avvisi in 3 pacchetti |
| Script di riproduzione dedicato | Assert dei comportamenti descritti superate |

L'avviso della suite riguarda l'uso di `httpx` nel TestClient Starlette. Le riproduzioni mostrano anche un avviso SQLAlchemy atteso durante la prova della transazione fallita.

Le evidenze consegnate sono [lo script](audit-2026-10-10/reproduce.py), [gli esiti delle riproduzioni](audit-2026-10-10/reproductions.json) e [il riepilogo dipendenze](audit-2026-10-10/dependencies-summary.json). Lo script contiene assert che documentano **i difetti attuali**: dopo le correzioni devono essere aggiornate per verificare il comportamento desiderato.

## 3. Rilievi di sicurezza e robustezza

### S-01 — Alta — I vecchi cookie sopravvivono al reset password

**Dove:** `mcorsi/models.py:44,73`; `mcorsi/extensions.py:41`; `mcorsi/settings/routes.py:112`; `mcorsi/auth/routes.py:25`; `mcorsi/cli.py:173`.

Il login memorizza l'identificativo stabile dell'utente. `set_password()` cambia soltanto l'hash; `load_user()` recupera l'account per quel medesimo identificativo. Non esiste una versione della sessione o un identificativo di autenticazione rotante che colleghi i cookie alla password corrente.

**Prova:** dopo login con “ricordami”, il cambio password lascia accessibile `/settings/` con risposta 200. Un nuovo client che riceve soltanto il vecchio cookie `remember_token` ottiene ancora 200. Durante la disabilitazione l'accesso viene correttamente respinto con redirect 302; dopo la riattivazione lo stesso client torna a ottenere 200 senza autenticarsi nuovamente.

**Impatto:** una sessione sottratta prima del reset continua a essere utilizzabile. La disabilitazione temporanea non revoca definitivamente le credenziali browser. Il cookie remember mantiene inoltre la durata predefinita Flask-Login di 365 giorni, perché l'app non configura `REMEMBER_COOKIE_DURATION`. Il solo `PERMANENT_SESSION_LIFETIME=8 ore` non accorcia tale cookie.

**Prerequisito:** possesso di un cookie valido preesistente; non è una tecnica per indovinare password o falsificare la firma.

**Correzione:** introdurre un `auth_id` casuale univoco o un `session_version`, cambiarlo a reset password, disabilitazione e revoca amministrativa, e validarlo a ogni richiesta e ripristino remember. Configurare una durata remember esplicita e una funzione di chiusura di tutte le sessioni. L'identificativo alternativo è il meccanismo suggerito dalla [documentazione Flask-Login](https://flask-login.readthedocs.io/en/latest/#alternative-tokens).

**Test di accettazione:** dopo reset, vecchia sessione e vecchio remember devono essere respinti; una successiva riattivazione non deve renderli validi.

### S-02 — Alta — Disabilitare il titolare non revoca i token MCP

**Dove:** `mcorsi/services/mcp_access.py:64`; `mcorsi/services/mcp_tools.py:24`; `mcorsi/mcp_server.py:32`; `mcorsi/settings/routes.py:137`; `mcorsi/cli.py:193`.

La verifica MCP controlla hash, stato e scadenza del token. `require_scope()` controlla lo scope e lo stato del token, ma non verifica che `access.created_by` sia ancora attivo e autorizzato. La disabilitazione dell'utente cambia soltanto `User.is_active`.

**Prova:** creato un token `courses:read`, disabilitato il suo amministratore titolare, eseguita una chiamata `tools/call` a `list_courses`: HTTP 200 e risultato senza `isError`. Anche `verify_access_token()` continua ad accettare il token.

**Impatto:** un accesso destinato a essere ritirato può proseguire tramite MCP. L'effetto dipende dagli scope concessi: lettura di corsi, dati partecipanti e attestati oppure accodamento di promemoria. Non è stata dimostrata un'escalation oltre gli scope assegnati.

**Correzione:** stabilire esplicitamente se i token sono credenziali personali o di servizio. Per token personali, verificare titolare attivo e ruolo autorizzato in entrambi i controlli, e revocare i token alla disabilitazione. Per credenziali di servizio, usare una distinta identità con un proprio ciclo di revoca, rendendo visibile questa differenza nell'amministrazione.

**Test di accettazione:** un token del titolare disabilitato deve essere respinto sul vero endpoint MCP; aggiungere anche il caso di rimozione del ruolo amministrativo.

### S-03 — Media — OTP a uso singolo e tentativi non sono atomici

**Dove:** `mcorsi/services/otp.py:148,301`; `mcorsi/models.py:204`.

La verifica legge `consumed_at` e `attempts`, li controlla in Python, poi incrementa il contatore e salva. Due sessioni SQLAlchemy possono leggere il medesimo stato iniziale prima che una delle due effettui il commit.

**Prova:** due thread con sessioni distinte sono sincronizzati nel calcolo dell'HMAC, dopo la lettura dei controlli. Con lo stesso codice corretto entrambi restituiscono successo; il database conserva `attempts=1`. Con due codici errati entrambe le chiamate falliscono, ma il database registra ancora un solo tentativo. La prova esegue realmente il servizio e i commit; la sincronizzazione forza l'interleaving e non cambia la logica di verifica.

**Impatto:** il codice non è rigorosamente a uso singolo e il massimo di cinque errori può essere aggirato attraverso tentativi concorrenti. Non è stata misurata la probabilità pratica di indovinare un OTP; il difetto non fornisce direttamente il codice.

Il servizio aziende usa lo stesso schema di lettura e aggiornamento, quindi presenta il medesimo rischio per analisi del codice; la riproduzione concorrente consegnata copre il servizio partecipanti.

**Correzione:** rendere consumo e incremento condizionali e atomici nel database, controllando il numero di righe aggiornate. Per SQLite valutare una breve transazione di scrittura serializzata; per altri DB usare locking coerente. Separare la validazione del codice dalla concessione della sessione in modo che soltanto una richiesta possa consumare la challenge.

**Test di accettazione:** due verifiche corrette concorrenti devono produrre un solo successo; due verifiche errate devono incrementare il contatore di due. Verificare anche l'emissione concorrente delle challenge, i cui limiti sono attualmente basati su conteggi seguiti da inserimenti.

### S-04 — Media — Il rollback del database non elimina il file caricato

**Dove:** `mcorsi/services/storage.py:204`; `mcorsi/documents/routes.py:81,116,271`; `mcorsi/imports/routes.py:19`.

`save_upload()` scrive il file e crea il record `StoredFile`. Le verifiche successive, come i segnaposto obbligatori del DOCX o le dimensioni della firma, avvengono dopo il salvataggio. Se falliscono, la route esegue `db.session.rollback()` senza eliminare il file già scritto.

**Prova:** un DOCX strutturalmente valido ma senza i segnaposto obbligatori viene rifiutato dalla route `/documents/templates`. A fine richiesta il database contiene zero record `StoredFile`, mentre nello storage rimane un DOCX.

**Impatto:** consumo progressivo di disco, file non censiti, aumento dei backup e difficoltà a eliminare dati che non hanno più un riferimento nel database. Il caricamento modelli richiede un amministratore; il problema analogo delle firme riguarda lo staff. Non è stata dimostrata una lettura anonima dei file orfani.

**Correzione:** validare in uno staging privato e spostare il file nello storage definitivo soltanto alla conclusione del flusso; in alternativa tracciare i file creati nella transazione e rimuoverli in caso di errore. Aggiungere una riconciliazione periodica fra file e record con soglie di conservazione prudenti.

**Test di accettazione:** DOCX senza segnaposto, firma troppo piccola e import Excel non valido devono lasciare invariati sia il numero di record sia il numero di file nello storage definitivo.

### S-05 — Media — Le notifiche aziendali ignorano lo stato di verifica

**Dove:** `mcorsi/services/notifications.py:47,110,128`; confronto con `mcorsi/services/permissions.py:44`.

L'accodamento del promemoria di scadenza controlla validità e verifica dell'attestato, ma per il destinatario aziendale controlla soltanto la presenza di un'azienda e della sua email. Non richiede `Company.verification_status == "verified"`, a differenza del portale.

**Prova:** un attestato verificato e in scadenza, associato a un'azienda in stato `rejected`, produce una notifica `certificate_expiry_company` indirizzata all'email dell'azienda rifiutata.

**Impatto:** nome del partecipante, titolo dell'attestato e scadenza possono essere comunicati a un indirizzo aziendale che non è più autorizzato. Lo scenario può verificarsi dopo il declassamento di un'azienda precedentemente verificata; non richiede la creazione di un attestato da parte di un visitatore anonimo.

**Correzione:** centralizzare la regola di autorizzazione delle comunicazioni aziendali, verificarla prima dell'accodamento e nuovamente prima dell'invio. Una notifica già in coda non deve sopravvivere a una revoca del destinatario senza rivalutazione.

**Test di accettazione:** nessun messaggio aziendale per stati `pending` o `rejected`; un messaggio accodato quando l'azienda era verificata deve essere cancellato o sospeso se lo stato cambia prima dell'invio.

### S-06 — Alta — pypdf vulnerabile usato direttamente sugli upload

**Dove:** `requirements.lock:883`; `mcorsi/services/storage.py:86`; `mcorsi/services/certificates.py:323`; `mcorsi/documents/routes.py:271`.

Il lockfile e l'ambiente corrispondente usano **pypdf 6.16.2**. Il contenuto caricato viene analizzato con `PdfReader` e accesso alle pagine nel thread HTTP, senza timeout del parser o limite di memoria di un processo separato.

Gli advisory confermano un difetto nei lunghi header degli oggetti indiretti, corretto in 6.18.0, e un difetto di decompressione di stream `/FlateDecode` malformati, corretto in 6.18.1. Queste operazioni possono entrare nella lettura strutturale del PDF: [advisory oggetti indiretti](https://github.com/py-pdf/pypdf/security/advisories/GHSA-5jq2-8x83-x246), [advisory FlateDecode](https://github.com/py-pdf/pypdf/security/advisories/GHSA-jw7q-gvrg-4vj3).

**Impatto:** possibile occupazione prolungata dei worker con file creati appositamente. Un partecipante autenticato può raggiungere il parser attraverso l'upload di attestati; l'OTP consente la registrazione autonoma. Il limite di 20 MB riguarda il file ricevuto, non il tempo o la memoria necessari a elaborarlo.

**Confidenza:** versione vulnerabile e percorso di chiamata confermati. Non è stato inviato un PDF ostile e non si afferma che tutti gli otto advisory pypdf siano sfruttabili: alcuni richiedono estrazione del testo, etichette di pagina, allegati o aggiornamento di form, operazioni non osservate in questi flussi.

**Correzione:** aggiornare pypdf a una versione che includa almeno le correzioni segnalate fino a 6.19.0, rigenerando entrambi i lockfile con hash e rieseguendo i test. Separare l'analisi dei PDF non fidati in un processo con timeout e budget di memoria. La correzione delle versioni non sostituisce i limiti di risorse.

**Test di accettazione:** audit dipendenze privo degli avvisi pypdf applicabili, upload valido funzionante e file di regressione malformati gestiti entro un tempo massimo senza bloccare il server.

### S-07 — Bassa — HTML non escapato nelle email OTP aziendali

**Dove:** `mcorsi/services/otp.py:282`; confronto con l'uso di `html.escape` in `mcorsi/services/notifications.py`.

La ragione sociale viene interpolata direttamente nel corpo HTML. Non viene applicato escape, mentre i promemoria corso lo applicano ai campi testuali.

**Prova:** una ragione sociale contenente un innocuo collegamento HTML di prova viene inserita nell'email come elemento `<a>`, senza codifica dei caratteri speciali.

**Impatto:** alterazione del contenuto della mail e possibile inserimento di link ingannevoli. Non è stato dimostrato XSS nel browser o esecuzione di script nei client email. L'azienda deve essere verificata per ricevere questo OTP; il rischio dipende quindi anche dalla revisione della sua anagrafica.

**Correzione:** usare un template HTML con autoescape o `html.escape(company.business_name)`. Trattare come testo tutti i valori dell'anagrafica.

**Test di accettazione:** `<`, `>`, `&` e virgolette della ragione sociale devono apparire codificati nel corpo HTML.

## 4. Bug funzionali e operativi

### B-01 — Media — Contatto principale inattivo causa un errore di unicità

**Dove:** `mcorsi/services/otp.py:187,206,253`; `mcorsi/models.py:343`.

La ricerca del contatto considera soltanto `is_active=True`. Se esiste un contatto inattivo ma l'email coincide con quella principale dell'azienda, la richiesta viene comunque ammessa. Il servizio cerca di inserire un nuovo contatto per la stessa coppia azienda/utente, violando `uq_company_contact_user`.

**Prova:** azienda verificata con email principale del suo contatto inattivo; `request_company_code()` solleva `IntegrityError`. La route non intercetta tale eccezione, quindi in esercizio la richiesta termina con errore 500.

Il vincolo impedisce la duplicazione: questa prova **non dimostra una riattivazione o un aggiramento della revoca**.

**Correzione:** cercare il contatto indipendentemente dallo stato e, se inattivo, respingere la richiesta. Riattivarlo soltanto con una decisione amministrativa esplicita. Gestire i conflitti concorrenti senza esporre un 500.

**Test:** contatto inattivo, email principale coincidente, nessuna challenge emessa e risposta pubblica uniforme.

### B-02 — Media — La pagina iniziale sceglie il ruolo azienda senza una sessione aziendale

**Dove:** `mcorsi/main/routes.py:65`; `mcorsi/portal/routes.py:57`; `mcorsi/services/otp.py:148,187`; `mcorsi/services/permissions.py:44`.

I ruoli `participant` e `company_contact` possono coesistere. Un login OTP partecipante non imposta `session["company_id"]`. La pagina `/` dà però precedenza a `company_contact` e reindirizza a `/company`, il cui controllo richiede proprio una sessione aziendale valida.

**Prova:** account con entrambi i ruoli, login partecipante riuscito, accesso alla home: redirect `/company`, seguito da 403. Il collegamento del marchio nella barra usa sempre la home, rendendo il problema visibile durante la navigazione normale.

**Correzione:** scegliere il portale in base al contesto di autenticazione attivo, controllando `company_id` prima del redirect aziendale; offrire una selezione esplicita dei portali quando l'utente ne possiede più di uno. Verificare anche che `profile_completed=True`, assegnato al primo account aziendale, non venga scambiato per un profilo partecipante completo dopo l'aggiunta di quel ruolo.

**Test:** login partecipante e login aziendale del medesimo account devono portare alle rispettive dashboard senza 403; testare profilo partecipante inizialmente assente.

### B-03 — Media — Invio duplicato delle notifiche con worker concorrenti

**Dove:** `mcorsi/services/notifications.py:128`; `mcorsi/models.py:178`.

`deliver_pending()` seleziona i messaggi pending, invia e soltanto dopo registra `sent`. Non esiste un claim esclusivo o uno stato di lavorazione. Due esecuzioni sovrapposte possono selezionare la medesima riga.

**Prova:** una riga pending, due thread con invio SMTP sostituito da una funzione in memoria e sincronizzato: due invii, entrambi i worker riportano `sent=1`.

**Impatto:** email duplicate e conteggi non rappresentativi dell'effettivo numero di messaggi elaborati. Il vincolo `unique_key` impedisce alcuni duplicati di accodamento, ma non risolve la concorrenza nell'invio. Anche un arresto dopo SMTP e prima del commit può causare un reinvio.

**Correzione:** claim atomico con lease e recupero dei job interrotti; impedire sovrapposizioni del processo pianificato. Definire la semantica di consegna: SMTP da solo non garantisce esattamente un invio in caso di arresto nel punto critico.

**Test:** due worker, una riga, un solo worker che acquisisce il job; test di recupero di lease scaduta.

### B-04 — Media — Verifica positiva per un backup senza database

**Dove:** `mcorsi/services/backup.py:281,302,344`.

La verifica controlla soltanto gli elementi elencati nel manifest. Non richiede la presenza di `database.sqlite3`, un elenco non vuoto, una corrispondenza completa con l'archivio o la dimensione dichiarata.

**Prova:** archivio con il solo `manifest.json`, `format_version=1` e `files=[]`: `verify_backup(..., allow_legacy_unencrypted=True)` restituisce successo. L'archivio non può essere ripristinato perché non contiene il database.

**Limite:** la prova usa l'opzione legacy esplicita. La verifica del manifest è però condivisa anche dal percorso cifrato. Non è stato dimostrato un aggiramento dell'autenticazione AES-GCM o la modifica di un backup senza chiave.

**Correzione:** validare la struttura del manifest, richiedere un unico database, confrontare dimensioni e checksum, respingere nomi duplicati e voci incoerenti. Distinguere verifica crittografica, verifica del contenitore e verifica di ripristinabilità; includere integrità SQLite e compatibilità dello schema quando si dichiara un backup ripristinabile.

**Test:** database assente, manifest vuoto, dimensione errata, nome duplicato e database non valido devono fallire.

### B-05 — Bassa — Il limite MCP viene applicato prima del filtro temporale

**Dove:** `mcorsi/services/mcp_tools.py:52`.

Il servizio ordina per creazione, applica `LIMIT`, poi elimina in Python i corsi passati. Un corso futuro fuori dalla prima finestra non viene considerato.

**Prova:** un corso futuro e un corso passato creato più recentemente, `upcoming_only=True, limit=1`: zero risultati, anche se nel database c'è un corso futuro.

**Correzione:** applicare il filtro sulle date prima del limite, con join alla seduta pertinente e conversione coerente del fuso orario; definire anche l'ordine atteso, per esempio data di svolgimento.

**Test:** una sequenza iniziale di corsi passati non deve nascondere i corsi futuri richiesti.

### B-06 — Media — Un errore di integrità lascia la sessione import in stato fallito

**Dove:** `mcorsi/services/imports.py:256`; `mcorsi/imports/routes.py:56`.

Il ciclo di import intercetta genericamente gli errori per marcare la riga come errata e continuare. Dopo un fallimento di `flush()`, però, SQLAlchemy richiede un rollback prima di riutilizzare la sessione. Il codice non usa savepoint per riga e prosegue sulla transazione invalidata.

**Prova:** simulato un conflitto di email durante il flush di una riga: il servizio termina con `PendingRollbackError`, invece di registrare correttamente l'errore di riga e completare il lotto. La simulazione inserisce un duplicato nel solo database di prova; non pretende di aver trovato un XLSX che provochi sempre questo conflitto in assenza di concorrenza.

**Impatto:** errore 500 e perdita del lavoro della transazione; il tentativo di continuare maschera la causa iniziale. Il comportamento necessario della sessione dopo un flush fallito è descritto nella [documentazione SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#flushing).

**Correzione:** transazione annidata/savepoint per riga, con intercettazione di errori attesi fuori dal savepoint. Per errori imprevisti interrompere l'import, fare rollback e registrare la causa. Non usare un generico `except Exception` per dichiarare recuperabile una transazione che non lo è.

**Test:** conflitto su una riga, riga successiva valida, conteggi e commit coerenti; nessuna `PendingRollbackError`.

### B-07 — Alta — Backup e startup scrivono sotto un percorso read-only nel deployment Linux

**Dove:** `mcorsi/__init__.py:73`; `mcorsi/services/backup.py:162,222`; `mcorsi/startup_secrets.py:18`; `deploy/linux/mcorsi-backup.service:8,13,15`; `deploy/linux/mcorsi.service:10,17,19`; `docs/DEPLOYMENT.md:35`.

Le unità systemd usano il progetto in `/opt/mcorsi`, `ProtectSystem=strict` e permettono scritture soltanto in `/var/lib/mcorsi` e `/var/backups/mcorsi`. L'applicazione, invece, usa l'instance path Flask predefinito, ossia `/opt/mcorsi/instance`, per creare la directory e per lo staging dei backup.

Cambiare database, storage e destinazione backup con le variabili documentate non cambia `app.instance_path`. La creazione/lettura dei backup cerca quindi di scrivere in `/opt/mcorsi/instance/backup-staging`, fuori dalle eccezioni read-write. Anche la migrazione dei segreti usa `.env` e marker nel progetto.

**Impatto:** backup pianificati non eseguibili con la configurazione fornita; se la directory instance manca, anche l'avvio può fallire. Il ripristino cifrato richiede lo stesso staging. La semantica di filesystem protetto ed eccezioni è descritta nel [manuale sorgente systemd](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml).

**Confidenza:** incompatibilità confermata per analisi statica; non è stato avviato systemd in questo ambiente Windows. Un deployment con override, bind mount o permessi aggiuntivi può evitare il problema, ma tali modifiche non sono nel modello consegnato.

**Correzione:** introdurre un instance/state path configurabile e impostarlo a `/var/lib/mcorsi`, usare `StateDirectory` dove appropriato e separare il file di configurazione protetto dalla migrazione operativa. Conservare lo staging nel percorso di stato autorizzato. Mantenere read-only la directory del codice.

**Test:** su Linux installare le unità senza override, avviare web/MCP e creare/verificare un backup come utente di servizio con tutte le protezioni attive.

### B-08 — Media — Il terzo tentativo aperto scompare dalla dashboard

**Dove:** `mcorsi/portal/routes.py:232,246`; `mcorsi/templates/portal/dashboard.html:12`; `mcorsi/services/questionnaires.py:171,215`.

`attempts_used()` conta anche i tentativi aperti. La dashboard offre il pulsante soltanto se i tentativi residui sono maggiori di zero. Quando si apre il terzo tentativo, il residuo diventa zero anche se quel tentativo è ancora valido e non è stato inviato.

**Prova:** due tentativi scaduti e un terzo aperto, con scadenza futura: la dashboard mostra “Tentativi esauriti” e nessuna azione `/start`. Il servizio `start_attempt()` sarebbe invece in grado di restituire il tentativo aperto.

**Impatto:** chi torna alla dashboard durante l'ultimo tentativo non può riprenderlo tramite la UI. Un URL conservato può consentire il recupero, quindi il tentativo non è cancellato; tuttavia il tempo continua a decorrere e può scadere inutilmente.

**Correzione:** distinguere tentativi residui per nuovi avvii e tentativo corrente riprendibile. Mostrare “Riprendi” con un link al tentativo aperto anche quando il residuo è zero.

**Test:** terzo tentativo aperto visibile e riprendibile; tentativo scaduto o inviato non riprendibile.

### B-09 — Alta — Il ripristino non ripristina lo storage se fallisce il secondo rename

**Dove:** `mcorsi/services/backup.py:344`, in particolare la sequenza di sostituzione dello storage intorno alle righe 402–415.

Lo storage corrente viene rinominato in `storage_old`. Successivamente `storage_new` viene spostato al percorso definitivo. Il blocco che ripristina lo storage precedente in caso di eccezione comincia soltanto dopo queste due operazioni.

**Prova:** creato un backup reale cifrato su dati sintetici; simulata una `PermissionError` soltanto sul rename di `storage_new`. Il percorso storage configurato risulta assente, mentre il precedente rimane in `.storage.before-restore-*`. Il database corrente non viene sostituito. La prova non elimina lo storage operativo.

**Impatto:** applicazione senza documenti al percorso previsto dopo un ripristino fallito. I dati precedenti sono ancora recuperabili manualmente, ma non viene garantita la coerenza di database e storage alla conclusione dell'operazione.

**Correzione:** racchiudere l'intera fase di sostituzione in un blocco di recupero, registrare le operazioni riuscite e ripristinare la coppia precedente se qualsiasi passaggio fallisce. Prevedere recupero anche in caso di arresto del processo fra i rename, mediante un journal dell'operazione.

**Test:** errori simulati su ogni rename, sulla sostituzione database e sulla pulizia; dopo ogni fallimento deve essere disponibile una coppia coerente di database e storage, senza interventi manuali nei casi recuperabili.

### B-10 — Bassa — Target non valorizzato nell'audit di creazione corso

**Dove:** `mcorsi/services/courses.py:78`; `mcorsi/services/audit.py:10`; `mcorsi/models.py:19,363`.

L'UUID viene assegnato al flush. `create_course()` registra l'evento prima di eseguire il flush della nuova entità; `record_event()` converte il valore `None` nella stringa `"None"`.

**Prova:** dopo commit il corso ha un UUID, ma l'evento `course.created` conserva `target_id="None"`.

**Impatto:** correlazione e interrogazione dell'audit meno affidabili. Il codice corso nel dettaglio dell'evento aiuta a ricostruire il collegamento, ma non sostituisce un target valido. Controllare gli altri eventi emessi prima del flush: questa prova riguarda specificamente il corso.

**Correzione:** assegnare l'UUID alla costruzione dell'entità oppure fare flush prima dell'evento. Non trasformare un identificativo mancante in una stringa apparentemente valida; validarlo per gli eventi che richiedono un target persistente.

**Test:** `course.created.target_id` deve coincidere con l'UUID del corso creato.

## 5. Dipendenze: avvisi e raggiungibilità

Il comando usato consulta gli advisory per le versioni del lockfile senza installare o aggiornare pacchetti:

```powershell
instance\lock-venv\Scripts\python.exe -m pip_audit --strict --require-hashes --disable-pip -r requirements.lock --cache-dir instance\audit-20261010\pip-audit-cache -f json -o instance\audit-20261010\dependencies.json
```

| Pacchetto | Versione fissata | Avvisi | Valutazione |
|---|---:|---:|---|
| pypdf | 6.16.2 | 8 | Alcune operazioni vulnerabili compatibili con la lettura degli upload; priorità S-06 |
| PyJWT | 2.13.0 | 14 | Dipendenza transitiva; non trovato uso di decode JWT nel percorso MCP autenticato esaminato |
| Werkzeug | 3.1.8 | 1 | Advisory Windows su nomi di dispositivo; primitiva accetta `NUL:`, ma endpoint locale restituisce 404 |

### pypdf

| CVE | Advisory | Versione corretta indicata dall'audit |
|---|---|---|
| CVE-2026-102993 | GHSA-qv6h-rv94-w285 | 6.17.0 |
| CVE-2026-102994 | GHSA-5jq2-8x83-x246 | 6.18.0 |
| CVE-2026-102995 | GHSA-fp3h-c4fm-7vvf | 6.18.1 |
| CVE-2026-102996 | GHSA-g9cg-prrw-2r8q | 6.18.1 |
| CVE-2026-102997 | GHSA-jw7q-gvrg-4vj3 | 6.18.1 |
| CVE-2026-102998 | GHSA-php9-fj8v-98fj | 6.19.0 |
| CVE-2026-102999 | GHSA-v247-6f48-mgcj | 6.19.0 |
| CVE-2026-103000 | GHSA-w23x-9jrw-r45c | 6.19.0 |

Per la valutazione di raggiungibilità e le fonti primarie si rimanda a S-06. Gli identificativi e le versioni provengono dall'output di pip-audit conservato negli allegati.

### PyJWT

L'autenticazione mCorsi usa token opachi HMAC nel database e un `DatabaseTokenVerifier`, non JWT applicativi. La ricerca nei sorgenti mCorsi e nei moduli server/client MCP dell'ambiente fissato non ha trovato chiamate `jwt.decode`. Pertanto non è stato dimostrato un bypass dell'autenticazione mCorsi tramite i 14 avvisi PyJWT.

Gli avvisi sono CVE-2026-101917, CVE-2026-101918, CVE-2026-102265, CVE-2026-102266, CVE-2026-102267, CVE-2026-102268, CVE-2026-102269, CVE-2026-102270, CVE-2026-102271, CVE-2026-102272, CVE-2026-102273, CVE-2026-102274, CVE-2026-102275 e CVE-2026-103001. Il JSON allegato contiene le associazioni GHSA e le versioni di correzione.

Undici avvisi indicano 2.14.0, due indicano 2.15.0 e uno non riporta una versione corretta. Per quest'ultimo, la [scheda del manutentore GHSA-gvp8-978c-rx2q](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-gvp8-978c-rx2q) mostra ancora “None” come versione corretta. Non è quindi corretto promettere che un aggiornamento nominale a 2.15.0 azzeri tutti gli avvisi. Verificare le schede correnti e rieseguire l'audit dopo l'aggiornamento.

### Werkzeug su Windows

[GHSA-g6x2-hccm-hh4m / CVE-2026-102598](https://github.com/pallets/werkzeug/security/advisories/GHSA-g6x2-hccm-hh4m) riguarda `safe_join` e nomi di dispositivo con suffisso ADS, con correzione in 3.1.9. Flask usa `send_from_directory` per la route statica predefinita.

La primitiva locale restituisce `C:/static/NUL:` anziché respingere il nome. Tuttavia, sul Python/Windows esaminato, `os.path.isfile` restituisce False e `/static/NUL:` termina con 404. **Non è stato riprodotto un blocco dell'endpoint** e non si conta questo avviso come un'ulteriore vulnerabilità applicativa confermata. Aggiornare comunque Werkzeug e verificare il comportamento sul server effettivo.

Gli avvisi dipendenze descrivono lo stato consultato il 10 ottobre 2026. Non sono stati aggiornati pacchetti o lockfile durante l'audit.

## 6. Rischi condizionati e approfondimenti

Questi elementi non sono inclusi nei 17 rilievi perché richiedono una verifica di deployment, una decisione di prodotto o una prova aggiuntiva.

### R-01 — Confine di fiducia del reverse proxy

`TRUST_PROXY_HEADERS` è disabilitato per default. Se attivato, `ProxyFix` accetta un livello di header inoltrati per IP, schema, host e porta (`mcorsi/__init__.py:77`). I launcher di produzione ascoltano normalmente su `0.0.0.0`.

Se la porta backend è raggiungibile direttamente da soggetti non fidati, questi possono fornire gli header che l'app usa per IP e host. Il rischio comprende alterazione dei log, elusione del limite per IP e costruzione di URL con host controllato. Il limite password per account rimane una protezione distinta. Se invece il proxy non è riconosciuto, tutti i visitatori del tunnel possono condividere l'IP del proxy nei contatori e nei log.

Verificare firewall e catena effettiva degli header; limitare il backend al proxy previsto e definire `TRUSTED_HOSTS`. Il corretto numero di proxy fidati è richiesto dalla [documentazione Flask](https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/). Non è stata verificata la configurazione Cloudflare operativa.

### R-02 — Upload senza quota cumulativa e viste senza paginazione

Il limite per richiesta è 20 MB, ma non sono presenti quote per utente, limite cumulativo di storage o throttling del caricamento attestati. Un partecipante può ripetere upload validi. Molte viste staff e relazioni usano `.all()` e caricano interi elenchi.

Valutare quote, limiti di frequenza, soglia minima di spazio libero e paginazione prima di ampliare l'accesso. Non è stato riempito il disco né misurato il limite di capacità. I limiti applicativi di risorse sono distinti dal solo limite di dimensione HTTP, come spiega la [documentazione Flask sulla sicurezza](https://flask.palletsprojects.com/en/stable/web-security/#resource-use).

### R-03 — Operazioni bloccanti nei worker web

Invio OTP SMTP, parsing PDF/XLSX e conversione LibreOffice avvengono sincronicamente. Waitress è avviato con quattro thread; LibreOffice può attendere fino a 90 secondi, SMTP fino al timeout configurato. Sotto concorrenza tali attività possono occupare tutti i worker.

Valutare code di lavoro, timeout complessivi e isolamento dei parser/converter. La sandbox Jinja impedisce molte forme di template injection, ma non isola il binario LibreOffice né le sue eventuali vulnerabilità. Non è stata esaminata la versione installata del converter o provata una SSRF tramite relazioni esterne DOCX.

### R-04 — Permessi sui file temporanei e chiavi di recupero

Il backup finale è cifrato e l'archivio ZIP temporaneo è creato con permessi POSIX 0600. La copia SQLite e i file di staging, però, sono creati tramite altre API e dipendono dai permessi ereditati/umask. Su Windows `chmod(0600)` non configura una ACL equivalente.

Verificare ACL e permessi delle directory instance, storage, backup-staging e dei file `.env.pre-secret-migration`. Conservare separatamente le chiavi di backup e quelle necessarie a decifrare i segreti SMTP dopo un ripristino: il backup include database e storage, non il file di configurazione completo. Non sono state ispezionate ACL o chiavi reali.

### R-05 — Restrizione sulle ammissioni aggirabile cambiando il referente

Le route di approvazione richiedono amministratore o referente. La modifica del corso, compreso `referent_user_id`, è però consentita a tutti gli operatori. Un operatore può quindi assumere il ruolo di referente e successivamente approvare.

La specifica autorizza gli operatori a modificare tutti i corsi: non si classifica automaticamente questa scelta come vulnerabilità. Chiarire se il limite sulle ammissioni rappresenti un vero confine di autorizzazione. In tal caso il cambio referente deve avere una politica più restrittiva.

### R-06 — Cache delle risposte private

Non è configurata una politica generale `Cache-Control: no-store` per pagine con dati personali e download. `send_file` usa validazione condizionale, che non equivale al divieto di conservare una copia locale.

Valutare una politica di cache esplicita per portali e attestati, soprattutto su dispositivi condivisi. Non è stata dimostrata una fuga attraverso una cache intermedia o una mancata protezione dell'autorizzazione alle richieste.

## 7. Protezioni presenti e differenze rispetto al vecchio audit

La revisione attuale contiene protezioni concrete che riducono diversi rischi segnalati nel report precedente:

| Area | Protezione osservata |
|---|---|
| OTP e privilegi staff | Emissione e verifica OTP respingono account admin/operator; nessun bypass password staff confermato |
| Modelli DOCX | Upload riservato agli admin, sandbox Jinja, verifica AST e allowlist dei campi |
| Segreti produzione | Avvio rifiutato per segreti mancanti, brevi, duplicati o chiavi Fernet non valide |
| Limiti accesso | Password limitate per IP e account; OTP limitati per account, IP e globalmente |
| Associazioni aziendali | Richieste partecipante pending e approvazione staff; accesso azienda richiede contatto attivo e azienda verificata |
| Sessione al login | `session.clear()` nei login password, OTP partecipante e OTP azienda |
| CSRF e redirect | Flask-WTF globale, logout POST, controllo del parametro `next` |
| File | UUID di storage, controllo contenimento percorso, MIME canonico e validazione reale del contenuto |
| Archivi Office | Limiti sul numero di voci e sul contenuto espanso, controlli sui percorsi, rifiuto macro note, XML defused |
| Download | Controlli di appartenenza per corsi/attestati, attachment e `nosniff` |
| Web | CSP, frame protection, Referrer-Policy, Permissions-Policy e HSTS quando i cookie sono Secure |
| SMTP | TLS richiesto per host remoti e verifica certificati con contesto SSL standard |
| Backup | Cifratura autenticata AES-GCM, checksum e copia SQLite tramite API backup |
| Deployment | Task Windows a livello Limited, unità Linux con utente dedicato e restrizioni systemd |
| Dipendenze | Lockfile con hash, dipendenze dev separate, workflow CI per audit e test |
| Dati | Vincoli per stati categoriali e unicità; tentativi questionario con scadenza e slot aperto univoco |
| Storico | Scelta esplicita della presenza, inizialmente pending; preservazione max_attempts nelle duplicazioni |

Il prototipo `app.py` indicato nel vecchio report non è presente nel checkout esaminato. Non si afferma che sia assente da altre installazioni.

Non sono emerse SQL injection o esecuzioni shell con input utente nei percorsi esaminati. I template web usano autoescape e non sono stati trovati filtri `safe` applicati a dati non fidati. Queste sono osservazioni del perimetro analizzato, non una prova generale di assenza di vulnerabilità.

## 8. Piano di correzione consigliato

### Priorità 1 — Revoca, parser PDF e recupero operativo

1. Implementare invalidazione di sessioni e remember al reset e alla disabilitazione (S-01).
2. Collegare validità dei token MCP allo stato dell'identità responsabile, oppure definire identità di servizio separate (S-02).
3. Aggiornare pypdf, Werkzeug e PyJWT compatibili, rigenerare i lockfile e ripetere l'audit senza ignorare automaticamente avvisi residui (S-06 e sezione 5).
4. Spostare instance/staging nei percorsi scrivibili del deployment Linux e provarlo con le unità reali (B-07).
5. Rendere recuperabile ogni fase della sostituzione database/storage nel ripristino (B-09).

### Priorità 2 — Concorrenza e gestione dati

1. Rendere atomici consumo e contatore OTP (S-03).
2. Aggiungere claim/lease alla consegna delle notifiche (B-03).
3. Applicare autorizzazione aziendale anche all'accodamento e alla consegna delle email (S-05).
4. Validare il manifest backup e la sua ripristinabilità (B-04).
5. Gestire rollback filesystem degli upload e savepoint delle righe import (S-04, B-06).

### Priorità 3 — Flussi UI e tracciabilità

Correggere il contatto aziendale inattivo, la scelta del portale, la ripresa dell'ultimo tentativo, il filtro MCP, l'escape email e gli identificativi dell'audit (B-01, B-02, B-08, B-05, S-07, B-10). Affrontare quote, proxy e permessi temporanei sulla base della configurazione effettiva.

### Criterio di chiusura

Ogni rilievo va chiuso soltanto dopo una correzione verificata con il relativo test di accettazione. La suite corrente, pur passando, deve essere estesa per coprire le condizioni qui riprodotte. La verifica finale deve includere una prova di backup e ripristino su un'installazione rappresentativa, oltre al controllo delle dipendenze aggiornate.

## 9. Riproducibilità

Eseguire dalla radice del progetto, usando un ambiente con le dipendenze di sviluppo fissate:

```powershell
instance\lock-venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-tmp\audit-20261010-locked
instance\lock-venv\Scripts\python.exe -m bandit -q -r mcorsi mcp_server.py wsgi.py
instance\lock-venv\Scripts\python.exe docs\audit-2026-10-10\reproduce.py
```

Il percorso `instance/lock-venv` è quello già disponibile nella macchina analizzata; su un altro checkout sostituirlo con l'interprete dell'ambiente di sviluppo equivalente. Le prove creano cartelle UUID nuove e lasciano i dati sintetici per l'ispezione. Gli esiti correnti sono salvati anche in `instance/audit-20261010/reproductions.json`; la copia allegata al report costituisce lo snapshot della revisione auditata.

Le prove di concorrenza impiegano barriere per rendere osservabile la finestra di race. B-06 e B-09 simulano errori nel solo ambiente di prova. La verifica Werkzeug testa soltanto la primitiva `safe_join`; il controllo HTTP separato ha restituito 404. Non sono inclusi payload PDF destinati a consumare risorse.

L'attività ha aggiunto il presente report e gli allegati. Non sono state applicate correzioni al codice, aggiornate dipendenze, eseguiti commit o modificati i file preesistenti dell'utente.
