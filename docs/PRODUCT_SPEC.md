# mCorsi — specifica di prodotto

Stato: prima release completata
Versione applicazione: 0.5.11
Versione database: 6
Lingua iniziale: italiano
Fuso orario predefinito: Europe/Rome

### Stato di sviluppo al 5 agosto 2026

Prima release implementata: autenticazione e portali, corsi e ammissioni,
questionari, documenti e attestati PDF, importazione storico XLSX, notifiche,
backup/ripristino, distribuzione Windows/Linux e server MCP autenticato.

### Volumi attesi

- 2–3 corsi al mese;
- 5–10 partecipanti per corso;
- circa 120–360 partecipazioni all'anno;
- un'unica installazione e un numero ridotto di accessi contemporanei.

Questi volumi non richiedono servizi distribuiti. SQLite in modalità WAL è
adeguato anche per la prima installazione in produzione, purché l'applicazione
usi un solo host, transazioni brevi e backup verificati. PostgreSQL resta una
possibilità futura e viene comunque supportato dalla configurazione.

## 1. Obiettivo

mCorsi è una web application mobile-first per organizzare corsi di formazione,
gestire ammissioni e partecipanti, somministrare questionari, produrre attestati
e renderli disponibili ai partecipanti e alle aziende di appartenenza.

L'applicazione deve funzionare su Windows durante lo sviluppo e su Windows o
Linux in esercizio. L'accesso esterno avviene attraverso Cloudflare Tunnel; il
server applicativo non espone direttamente porte pubbliche.

## 2. Ruoli

### Amministratore

- possiede anche tutte le funzioni di un operatore;
- crea, abilita e disabilita operatori;
- assegna e modifica il nome mostrato nell'interfaccia, mantenendo la mail come
  username;
- imposta o reimposta le password degli operatori;
- gestisce SMTP, impostazioni generali e autorizzazioni MCP;
- gestisce aziende, referenti aziendali e richieste di accesso aziendale;
- accede all'audit log e alle funzioni di backup/ripristino;
- può intervenire su ogni corso, ammissione, questionario e attestato.

### Operatore

- accede con email e password;
- può creare, modificare e duplicare qualsiasi corso;
- può gestire documenti, questionari e modelli di attestato;
- se referente di un corso, decide sulle richieste di ammissione;
- conferma la frequenza e genera gli attestati;
- può correggere aziende e partecipanti nei limiti previsti.

### Partecipante

- accede con email e codice OTP inviato tramite SMTP;
- al primo accesso completa l'anagrafica obbligatoria;
- chiede l'ammissione mediante il codice univoco del corso;
- consulta documenti e compila i questionari dei corsi ammessi;
- consulta e scarica i propri attestati;
- aggiorna contatti e preferenze per i promemoria.

### Referente aziendale

- accede indicando email e partita IVA, poi verifica un OTP via email;
- deve essere un contatto autorizzato dell'azienda;
- vede e scarica soltanto gli attestati associati alla propria azienda;
- non vede risposte o punteggi dei questionari né attestati personali riferiti
  ad altre aziende.

### Account tecnico

- usa token Bearer revocabili e scope granulari per MCP e automazioni;
- non può accedere a password, OTP, configurazione SMTP o firme;
- ogni attività è tracciata.

Una stessa identità email può avere più ruoli.

## 3. Autenticazione e sicurezza degli account

### Amministratori e operatori

- email normalizzata e univoca come username;
- password di almeno 8 caratteri con maiuscola, minuscola, numero e carattere
  speciale, memorizzata con hashing robusto;
- reimpostazione da amministratore e, successivamente, recupero via email;
- sessioni protette, cookie Secure/HttpOnly/SameSite e protezione CSRF;
- blocco temporaneo e rate limiting dopo ripetuti errori;
- disattivazione senza cancellazione dell'account.

### Partecipanti

- richiesta OTP con risposta generica, senza rivelare l'esistenza dell'account;
- codice casuale, monouso, conservato soltanto come hash;
- scadenza indicativa di 10 minuti;
- massimo numero di verifiche e richieste configurabile;
- al primo OTP valido viene creata o attivata l'identità;
- finché il profilo è incompleto sono accessibili solo onboarding e logout.

### Aziende

- partita IVA normalizzata più email del contatto;
- OTP inviato soltanto a un contatto già autorizzato;
- il primo referente di un'azienda non verificata richiede approvazione;
- risposte generiche impediscono l'enumerazione di aziende e contatti.

### Telefono e WhatsApp futuro

- numero mobile facoltativo, normalizzato in formato internazionale;
- campi separati per verifica, consenso e preferenza del canale;
- nella prima versione OTP e notifiche sono soltanto email;
- un futuro provider WhatsApp userà lo stesso servizio OTP/notifiche.

## 4. Profili e aziende

### Dati del partecipante

- nome e cognome;
- luogo e data di nascita;
- codice fiscale facoltativo;
- email verificata;
- telefono facoltativo;
- titolo da usare sull'attestato facoltativo;
- azienda corrente, quando applicabile.

### Azienda

- ragione sociale;
- indirizzo, CAP, comune, provincia e nazione;
- partita IVA univoca;
- codice fiscale;
- email;
- PEC facoltativa;
- stato di verifica e provenienza del dato.

Se una partita IVA non esiste, il partecipante inserisce i dati dell'azienda.
Sia l'azienda sia l'associazione restano `da verificare`: soltanto lo staff può
rendere effettiva la relazione, dopo avere verificato l'azienda e la richiesta.
Per le partite IVA italiane il sistema controlla formato e cifra di controllo.

La relazione lavorativa tra partecipante e azienda è separata dall'anagrafica.
Gli attestati conservano uno snapshot immutabile dei dati aziendali usati al
momento dell'emissione.

## 5. Corsi ed edizioni

Ogni corso/edizione comprende:

- titolo, descrizione, riferimenti legislativi e argomenti trattati;
- codice univoco non prevedibile;
- creatore e referente;
- stato: bozza, aperto, in corso, concluso, annullato, archiviato;
- una seduta nella prima versione;
- data, ora iniziale, ora finale e fuso orario;
- modalità e collegamento Meet facoltativi;
- durata di validità dell'attestato in mesi oppure nessuna scadenza;
- documenti allegati;
- uno o più questionari;
- modello e firmatario dell'attestato.

Il modello dati supporta più sedute fin dall'inizio, anche se la prima UI ne
consente una sola. Tutti gli operatori possono modificare tutti i corsi; le
modifiche rilevanti sono registrate nell'audit log.

### Duplicazione

La duplicazione crea una nuova edizione in bozza e copia:

- dati generali, riferimenti legislativi, argomenti, referente modificabile e validità;
- documenti tramite riferimenti a file immutabili;
- questionari come nuove versioni indipendenti;
- modello attestato e firmatario.

Vengono invece rigenerati codice, date e identificativi. Non vengono copiati
richieste, partecipanti, tentativi, presenze o attestati.

## 6. Ammissioni e frequenza

Il partecipante inserisce il codice e crea una richiesta `in attesa`. Il
referente può approvare o rifiutare, aggiungendo una nota interna e una
motivazione eventualmente visibile. L'amministratore può intervenire sempre.

Una richiesta approvata crea l'iscrizione. Per la prima versione la frequenza è
un esito singolo: da confermare, frequentato, non frequentato. La futura
gestione multiseduta introdurrà presenze per ogni incontro.

## 7. Questionari

- scelta singola o scelta multipla;
- punteggio configurabile per ogni opzione corretta;
- nella scelta multipla vengono sommati i punti delle opzioni corrette
  selezionate, consentendo un risultato parziale;
- la selezione di almeno un'opzione errata azzera il punteggio dell'intera
  domanda, impedendo il vantaggio della selezione indiscriminata;
- soglia minima configurabile per questionario;
- massimo tre tentativi;
- risposte, punteggi, orari ed esiti conservati per ogni tentativo;
- dopo tre insuccessi servono reset o autorizzazione di referente/admin;
- tutti i questionari obbligatori devono essere superati per l'attestato.

Le risposte corrette non vengono esposte ai partecipanti né al server MCP.
Un questionario pubblicato può essere sospeso e modificato soltanto finché non
esistono tentativi. Dopo il primo tentativo domande, punteggi e soglia sono
bloccati; ogni tentativo conserva inoltre uno snapshot dei dati valutati.

Gli operatori dispongono di un archivio trasversale filtrabile per corso e
stato, con anteprima identica alla compilazione del partecipante. Un
questionario può essere duplicato nello stesso corso o in un altro: la copia è
indipendente, in bozza e non contiene tentativi.

La definizione completa può essere esportata e reimportata come JSON nel formato
versionato `mcorsi.questionnaire`. Il trasferimento comprende domande, opzioni,
soluzioni e punteggi, ma esclude identificativi interni, tentativi, risultati e
dati personali. Ogni importazione produce una bozza e applica le stesse
validazioni del builder. È disponibile anche un'esportazione Markdown leggibile
per revisione o stampa; contenendo le soluzioni, è riservata agli operatori e
non è un formato di importazione.

## 8. Attestati

Gli utenti autorizzati caricano modelli DOCX con segnaposto. Il sistema valida
il modello, genera un'anteprima, inserisce dati e firma PNG trasparente e usa
LibreOffice headless per produrre il PDF finale.

Ogni attestato contiene o registra:

- identificativo e numero univoci;
- corso, partecipante, azienda e firmatario come snapshot;
- riferimenti legislativi e argomenti trattati come snapshot;
- data di emissione e scadenza calcolata dalla fine del corso;
- versione del modello;
- hash SHA-256 del PDF;
- stato: emesso, sostituito, revocato.

La generazione richiede corso concluso, frequenza confermata, profilo completo
e questionari obbligatori superati. È avviata esplicitamente dal referente o
dall'amministratore, singolarmente o in blocco.

La pagina partecipante/azienda mostra sinteticamente, per esempio:

`Corso effettuato marzo 2026 · scadenza marzo 2031`.

Sono previsti indicatori valido, in scadenza, scaduto e senza scadenza.

La firma è inizialmente un'immagine. Il renderer e il firmatario sono astratti
per consentire una futura firma digitale remota/PAdES.

## 9. Documenti e file

- file conservati fuori dalla directory pubblica e serviti solo dopo controllo
  delle autorizzazioni;
- nomi fisici casuali, metadati e hash nel database;
- corrispondenza obbligatoria tra estensione e contenuto reale, con MIME
  normalizzato dal server senza fidarsi dell'header del browser;
- limiti strutturali per contenitori Office/OpenDocument e rifiuto di ZIP
  cifrati, percorsi anomali e carichi espansi eccessivi;
- rifiuto di DOCM e altri formati con macro;
- documenti e modelli versionati e non modificati retroattivamente;
- possibilità futura di storage S3 compatibile e scansione antivirus.

## 10. Notifiche

La prima versione usa SMTP configurabile dall'amministratore:

- host, porta, username, password cifrata;
- nessuna cifratura, STARTTLS o SSL/TLS;
- mittente, reply-to e timeout;
- test di connessione e invio;
- credenziale mai mostrata dopo il salvataggio.

Un outbox nel database registra messaggi, tentativi e consegne ed evita duplicati.
Un worker separato e multipiattaforma invia OTP e promemoria.

La prima release invia promemoria per corso imminente e attestato in scadenza.
Variazioni, ammissione, questionario da completare, tentativi esauriti e nuovo
attestato sono estensioni previste.

## 11. Importazione dello storico

La prima versione importa manualmente file XLSX di Microsoft Forms. Vengono
considerati soltanto:

- identità e anagrafica del partecipante;
- azienda dichiarata come testo da verificare;
- data della compilazione;
- corso e data proposti dal nome file e confermati dall'operatore.

Domande, risposte e punteggi non vengono importati. Il corso storico è creato
come concluso, le presenze sono confermate e la valutazione pregressa è
considerata acquisita su conferma dell'operatore. Gli attestati sono quindi
generabili senza tentativi di questionario; restano obbligatori l'anagrafica
completa del partecipante e un modello attestato assegnato al corso.

L'importazione:

- legge le tabelle interne senza fidarsi della sola dimensione del foglio;
- mostra anteprima e mapping delle colonne;
- riconcilia prima codice fiscale, poi email, poi dati anagrafici;
- non unisce automaticamente persone basandosi soltanto sul nome;
- conserva file sorgente, hash, righe originali e audit batch;
- è idempotente e può essere annullata prima della conferma.

Sviluppi successivi: cartella OneDrive/SharePoint con Power Automate, Microsoft
Graph, Google Meet REST API e comandi Copilot Studio via MCP.

## 12. Portale aziendale

Il referente aziendale vede solo attestati il cui snapshot aziendale appartiene
alla sua azienda. Può cercare per dipendente, corso, data, scadenza e stato e
scaricare PDF singoli o, in seguito, un archivio ZIP.

Non può modificare utenti o attestati e non vede formazione personale legata ad
altre aziende. Ogni visualizzazione e download viene tracciato.

## 13. MCP e assistenti AI

Un server MCP Python separato, esposto via Streamable HTTP e token Bearer
revocabili, serve client API ChatGPT, Claude API e Claude Code. Condivide il
livello dei servizi applicativi con Flask e CLI, senza accesso SQL generico.

Prima versione prevalentemente consultiva e di preparazione:

- elenco e dettaglio corsi;
- riepilogo operativo e ammissioni pendenti;
- stato iscritti, profili, questionari e idoneità attestati;
- consultazione della coda email;
- accodamento idempotente dei promemoria dovuti.

Ammissioni, invii, emissione/revoca attestati, eliminazioni e gestione utenti
restano nella webapp. Gli account tecnici usano scope minimi, scadenza e audit.
OAuth 2.1 per collegare direttamente l'app nell'interfaccia ChatGPT è previsto
come evoluzione; la prima release è server-to-server.

## 14. Interfaccia

Interfaccia Flask/Jinja mobile-first con CSS locale, HTMX e piccoli componenti
Alpine.js dove utili. Nessuna dipendenza obbligatoria da CDN in produzione.

- pagina iniziale comune con accessi evidenti per operatori, partecipanti e aziende;
- navigazione laterale desktop e compatta mobile;
- dashboard diverse per ruolo;
- procedure guidate per onboarding, corso, questionario e importazione;
- tabelle responsive per operatori, schede per partecipanti;
- questionari touch-friendly con stato e tentativi chiari;
- conformità WCAG 2.1 AA come obiettivo;
- PWA installabile futura, senza cache offline di dati sensibili.

## 15. Amministrazione da riga di comando

Comandi previsti:

- `flask admin create`;
- `flask admin set-password EMAIL`;
- `flask admin create-operator`;
- `flask admin disable-user`;
- `flask admin list-users`;
- `flask backup create`, `list`, `verify` e `restore`;
- `flask mcp token-create`, `token-list` e `token-revoke`.

Le password sono richieste con input nascosto e mai passate come argomento CLI.

## 16. Privacy, audit e conservazione

- minimizzazione dei dati e informative specifiche per partecipanti e aziende;
- consensi separati per canali facoltativi come WhatsApp;
- esportazione dei dati personali e procedura di rettifica;
- cancellazione logica/anominizzazione compatibile con obblighi documentali;
- audit di login, configurazioni, corsi, ammissioni, attestati, import e download;
- nessun segreto nei log;
- politica di conservazione configurabile;
- backup con checksum e prova periodica di ripristino.

### Backup e ripristino

Il backup comprende database SQLite, documenti dei corsi, modelli, firme,
attestati, file di importazione e un manifest con versione e checksum. L'intero
archivio è cifrato e autenticato a blocchi con AES-256-GCM e una chiave dedicata.

- creazione manuale da CLI e pagina amministrativa;
- pianificazione giornaliera facoltativa tramite worker;
- destinazione configurabile, anche disco esterno o percorso di rete;
- nome archivio con data/ora e identificativo installazione;
- uso dell'API backup di SQLite per ottenere una copia coerente a sistema attivo;
- verifica automatica dell'archivio dopo la creazione;
- conversione non distruttiva dei backup legacy non cifrati;
- conservazione configurabile, inizialmente ultimi 30 backup;
- elenco e verifica disponibili da CLI;
- ripristino solo da CLI, con applicazione ferma, conferma esplicita e copia di
  sicurezza preventiva dello stato corrente.

Le chiavi master dell'installazione non vengono inserite nello stesso archivio:
devono essere conservate separatamente in un luogo sicuro. Una copia sullo
stesso disco della macchina non è considerata un backup sufficiente.

## 17. Decisioni tecniche

- Python e Flask;
- architettura modulare con application factory e blueprint;
- SQLAlchemy e Alembic;
- SQLite per sviluppo, test e prima installazione a basso volume;
- PostgreSQL disponibile come evoluzione senza cambiare la logica applicativa;
- rendering Jinja e progressive enhancement;
- Waitress per sviluppo/Windows, server WSGI equivalente su Linux;
- Cloudflare Tunnel verso localhost;
- storage locale privato nella prima versione;
- test automatici con pytest.

## 18. Roadmap

### Fase 1 — Fondazioni

Struttura Flask, configurazione, database, migrazioni, account, ruoli, login
operatori, CLI amministrativa, layout responsive, test e audit base.

### Fase 2 — Partecipanti e aziende

OTP email, onboarding, aziende, relazioni lavorative, referenti aziendali e
preferenze notifiche.

### Fase 3 — Corsi

Corsi/sedute, duplicazione, documenti, codici, richieste, decisioni e frequenza.

### Fase 4 — Questionari

Editor, risposte singole/multiple, tentativi, punteggi e soglie.

### Fase 5 — Attestati

Modelli DOCX, anteprima, PDF, firma immagine, scadenze, verifica e portali.

### Fase 6 — Storico e notifiche

Import XLSX, reminder, outbox e worker.

### Fase 7 — Esercizio

Cloudflare, configurazione Linux/Windows, SQLite WAL, backup, monitoraggio e
hardening di sicurezza.

### Fase 8 — MCP e automazioni

Server MCP, token con scope, ChatGPT API, Claude e job programmati sono
completati. OAuth 2.1 per il collegamento diretto nell'interfaccia ChatGPT resta
un'estensione successiva.

## 19. Criteri per la prima release

La prima release è pronta quando un amministratore può creare operatori,
configurare SMTP, creare e duplicare un corso, approvare partecipanti, registrare
la frequenza, far compilare i questionari da mobile, generare attestati PDF e
renderli disponibili a partecipanti e aziende, con audit e backup verificati.
