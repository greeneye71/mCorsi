# Iscrizione diretta al corso con codice — design

Data: 2026-11-14 · Stato: approvato

## Intento

Oggi il referente iscrive i partecipanti a mano, oppure il partecipante inserisce il
codice del corso e crea una richiesta di ammissione `pending` che il referente deve
approvare. Per i corsi in aula con molti partecipanti questo passaggio è lento: il
partecipante riceve il codice, entra con email + OTP e deve poter sostenere il test
subito, senza attendere un'approvazione.

Serve una **modalità aggiuntiva**, attivabile per singolo corso: chi conosce il codice
si iscrive da solo, conferma o aggiorna i propri dati e viene iscritto
automaticamente, così può svolgere il questionario.

## Obiettivi

- Opzione per corso "Iscrizione diretta con codice" (spenta di default).
- Con l'opzione attiva e corso `open` o `in_progress`, il codice iscrive subito.
- Il partecipante senza iscrizioni attive viene portato all'inserimento del codice.
- Prima dell'iscrizione il partecipante conferma o aggiorna il profilo (precompilato).
- Contro la forza bruta: ritardo progressivo dopo ogni codice errato.
- Ogni iscrizione diretta lascia traccia nell'audit.

## Non obiettivi

- Nessun cambio all'accesso email + OTP.
- Nessun cambio all'iscrizione manuale del referente né all'approvazione delle richieste.
- Nessun codice per partecipante, nessun QR, nessun limite di posti.
- Nessuna rigenerazione del codice del corso (eventuale lavoro futuro).

## Anti-obiettivi (sarebbe un fallimento anche se funziona)

- Dati aziendali verificati sovrascritti da ciò che scrive il partecipante.
- Corso chiuso (`completed`, `canceled`, `archived`) o in bozza (`draft`) raggiungibile col codice.
- Messaggi di errore che permettono di capire se un codice esiste.
- Il server che "dorme" per applicare il ritardo (blocca uno dei 4 thread di Waitress).

## Approcci considerati

- **A — Opzione per corso (scelto dall'utente).** Nuovo flag sul corso. Acceso: il
  codice iscrive subito. Spento: comportamento attuale (richiesta `pending`).
  Il referente sceglie corso per corso; nessun impatto sui corsi esistenti.
- **B — Iscrizione diretta sempre attiva.** Ogni codice valido iscrive subito, le
  richieste di ammissione spariscono dal flusso del partecipante. Più semplice, ma
  toglie al referente il controllo sui corsi in cui vuole approvare a mano.

## Decisioni

### Dati

- `Course.self_enrollment_enabled` — `Boolean`, `nullable=False`, default `False`
  (`server_default` falso), con migrazione Alembic dopo l'head attuale.
- Nuova tabella `course_code_failures` per il ritardo:
  - `id`, `scope` (`"user"` | `"ip"`), `subject` (id utente o indirizzo IP),
    `failures` (int), `last_failure_at`, `blocked_until` (datetime con fuso).
  - Vincolo unico su (`scope`, `subject`).

### Form del corso

- `CourseForm` riceve la checkbox "Iscrizione diretta con codice" con testo d'aiuto:
  "Chi inserisce il codice viene iscritto subito, finché il corso non è chiuso."
- `_course_form_data` la salva; visibile in creazione e modifica.
- La pagina di dettaglio del corso mostra se l'opzione è attiva accanto al codice.

### Stati ammessi

| Stato corso | Flag acceso | Flag spento |
|-------------|-------------|-------------|
| `open` | iscrizione immediata | richiesta `pending` (come oggi) |
| `in_progress` | iscrizione immediata | rifiuto (come oggi) |
| `draft`, `completed`, `canceled`, `archived` | rifiuto | rifiuto |

Il rifiuto usa sempre lo stesso messaggio generico già presente:
"Codice non valido o corso non aperto alle richieste."

### Flusso del partecipante

1. Login email + OTP (invariato).
2. Se il partecipante **non ha iscrizioni a corsi attivi** (`open`/`in_progress`) e
   nessuna richiesta `pending`, la dashboard mostra in cima, in evidenza, il riquadro
   "Inserisci il codice del corso". Chi ha già corsi attivi vede la dashboard di oggi,
   con il riquadro codice nella posizione attuale.
3. Inserimento codice:
   - errato o corso non ammesso → messaggio generico, conteggio errore, ritardo;
   - flag spento e corso `open` → richiesta `pending` (come oggi);
   - flag acceso e stato ammesso → l'id del corso va in sessione
     (`pending_self_enrollment`) e redirect alla pagina di conferma.
4. Pagina di conferma = form del profilo esistente, precompilato, con in testa
   "Stai per iscriverti a: <titolo corso>" e pulsante "Conferma e iscriviti".
   - Riusa la logica di `profile` (azienda nuova, `request_company_association`,
     `profile_completed=True`): l'associazione all'azienda resta da verificare come
     oggi, i dati verificati non vengono toccati.
   - Al salvataggio: aggiornamento profilo + iscrizione nella stessa transazione,
     rimozione della chiave di sessione, redirect alla dashboard con messaggio
     "Iscrizione completata: puoi svolgere il questionario."
5. Il partecipante con profilo incompleto può inserire il codice **prima** di
   completare il profilo: la pagina di conferma è proprio il completamento del profilo.
   Senza codice in sessione, il comportamento attuale (redirect a `profile`) resta.

All'invio della conferma lo stato del corso e il flag vengono **ricontrollati**: se nel
frattempo il corso è stato chiuso o il flag spento, niente iscrizione e messaggio generico.

### Iscrizione (servizio)

Nuova funzione `self_enroll(course, participant)` in `mcorsi/services/courses.py`:

- verifica flag e stato ammesso, altrimenti `CourseOperationError`;
- se esiste già un'`Enrollment` per (corso, partecipante) → nessuna duplicazione,
  messaggio "Sei già iscritto a questo corso.";
- se esiste un'`AdmissionRequest`:
  - `pending` → viene approvata tramite `decide_admission(..., actor=participant, approve=True)`;
  - `rejected` → rifiuto con messaggio "La tua richiesta per questo corso è stata
    respinta: contatta il referente." (un rifiuto del referente non si scavalca col codice);
- altrimenti crea l'`AdmissionRequest` e la approva subito con `decide_admission`,
  attore il partecipante, `decision_message="Iscrizione diretta con codice"`;
- registra l'evento audit `enrollment.self_enrolled` (corso, partecipante, IP tramite
  `record_event`), oltre a quelli già emessi da `request_admission`/`decide_admission`.

Passare dall'`AdmissionRequest` approvata mantiene visibile il corso nella dashboard
(che oggi elenca le richieste) e nel registro del referente.

### Ritardo progressivo contro la forza bruta

- Si conta un errore per ogni codice che non porta a iscrizione o richiesta
  (codice inesistente **o** corso in stato non ammesso: stesso trattamento, nessuna
  informazione trapela).
- Conteggio separato per utente e per IP; vale il blocco più lungo dei due.
- Ritardo dopo l'errore n: 0 s al primo, poi 2, 4, 8, 16 … secondi, massimo 300 s
  (`min(300, 2 ** (n - 1))` per n ≥ 2).
- Durante il blocco la richiesta viene rifiutata **subito**, senza verificare il codice,
  con il messaggio "Troppi tentativi: riprova tra N secondi." (nessun `sleep`).
- Azzeramento: codice valido (per utente e IP) oppure 1 ora senza errori.
- IP preso da `request.remote_addr` (già corretto da `ProxyFix` dietro il tunnel).
- Logica in un modulo dedicato, es. `mcorsi/services/course_code_throttle.py`,
  sul modello di `OtpRateLimitError` in `services/otp.py`.
- Vale anche per il flusso con flag spento (oggi senza alcun limite).

### Audit

- `enrollment.self_enrolled` all'iscrizione diretta.
- `course_code.failed` all'errore (utente, IP, numero errori; **mai** il codice digitato,
  per non registrare tentativi di indovinare codici altrui).
- Modifica del flag sul corso: già coperta dall'audit di aggiornamento del corso, se presente;
  altrimenti evento `course.self_enrollment_changed`.

## Test (pytest, nello stile esistente)

- Migrazione: colonna presente, default falso sui corsi esistenti.
- Form corso: la checkbox si salva in creazione e modifica.
- Flag acceso + `open` e + `in_progress` → `Enrollment` creata, `AdmissionRequest` approvata, evento audit.
- Flag acceso + `draft`/`completed`/`canceled`/`archived` → rifiuto con messaggio generico.
- Flag spento + `open` → richiesta `pending` come oggi; + `in_progress` → rifiuto.
- Già iscritto → nessun duplicato. Richiesta `pending` esistente → approvata. Richiesta `rejected` → rifiuto.
- Profilo incompleto: codice → conferma → profilo completo + iscrizione.
- Conferma dopo chiusura del corso o spegnimento del flag → niente iscrizione.
- Dati aziendali verificati non modificati dalla conferma.
- Ritardo: 1° errore senza blocco; 2°, 3° con 2 s e 4 s; tetto a 300 s; blocco per IP con utenti diversi;
  azzeramento dopo successo e dopo 1 ora (tempo simulato); risposta immediata durante il blocco.
- Dashboard: senza corsi attivi il riquadro codice è in evidenza.

## Lasciato a chi implementa

- Testi esatti dell'interfaccia oltre a quelli indicati, posizione grafica del riquadro.
- Nomi interni di funzioni e template (es. `portal/confirm_enrollment.html` o
  riuso di `profile.html` con un parametro).
- Pulizia delle righe di `course_code_failures` scadute (opzionale, es. al momento della lettura).
