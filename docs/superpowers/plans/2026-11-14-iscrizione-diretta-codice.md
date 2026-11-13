# Iscrizione diretta con codice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opzione per corso che, inserendo il codice, iscrive subito il partecipante dopo la conferma del profilo, con ritardo progressivo contro la forza bruta.

**Architecture:** Flag `Course.self_enrollment_enabled` + tabella `course_code_failures`. Il servizio `self_enroll` riusa `request_admission`/`decide_admission`; il throttle vive in `mcorsi/services/course_code_throttle.py` e non dorme mai (calcola `blocked_until`). Nel portale, `add_admission` smista fra richiesta `pending` e pagina di conferma; la conferma riusa `profile.html` e una funzione estratta da `profile()`.

**Tech Stack:** Flask, Flask-WTF, Flask-Login, SQLAlchemy, Alembic (Flask-Migrate), pytest.

**Spec:** `docs/superpowers/specs/2026-11-14-iscrizione-diretta-codice-design.md`

## Global Constraints

- Messaggio di rifiuto unico: `"Codice non valido o corso non aperto alle richieste."`
- Stati ammessi per iscrizione diretta: `open`, `in_progress` (solo con flag acceso). Flag spento: solo `open` → richiesta `pending`.
- Ritardo dopo errore n: 0 per n=1, `min(300, 2 ** (n - 1))` per n ≥ 2. Azzeramento su codice valido o dopo 1 ora senza errori.
- Messaggio blocco: `"Troppi tentativi: riprova tra N secondi."` — risposta immediata, nessun `time.sleep`.
- Audit `course_code.failed` con utente, IP, numero errori; **mai** il codice digitato.
- Audit `enrollment.self_enrolled` a ogni iscrizione diretta.
- Testi: checkbox "Iscrizione diretta con codice", aiuto "Chi inserisce il codice viene iscritto subito, finché il corso non è chiuso.", intestazione "Stai per iscriverti a: <titolo>", pulsante "Conferma e iscriviti", flash finale "Iscrizione completata: puoi svolgere il questionario.", "Sei già iscritto a questo corso.", "La tua richiesta per questo corso è stata respinta: contatta il referente."
- Chiave di sessione: `pending_self_enrollment` (id corso).
- Dati aziendali verificati mai sovrascritti (riusare la logica azienda esistente di `profile()` senza modificarla).
- Commit in italiano, imperativo.

## Review Focus

1. Partecipante con codice in sessione che riapre la dashboard o il profilo prima di confermare → nessuna iscrizione fantasma; la conferma resta raggiungibile, il profilo normale non iscrive. (Task 5: `test_profile_save_does_not_enroll_with_pending_code`)
2. Codice con minuscole/spazi (`abcd 234567`) → normalizzato come oggi con `normalize_identifier`, vale anche per l'iscrizione diretta. (Task 5: `test_self_enroll_accepts_lowercase_code`)
3. Form della conferma non valido (P.IVA errata) → pagina rimostrata con errori e intestazione corso, nessuna iscrizione, sessione intatta. (Task 5: `test_confirm_invalid_vat_keeps_pending_course`)
4. Codice valido mentre il blocco è attivo → rifiutato comunque senza toccare il DB del corso (il blocco precede la ricerca). (Task 5: `test_valid_code_rejected_while_blocked`)
5. Riga di errore vecchia di oltre 1 ora con `blocked_until` nel passato → il prossimo errore conta come primo (nessun ritardo). (Task 3: `test_failures_expire_after_one_hour`)

---

### Task 1: Modello e migrazione

**Files:**
- Modify: `mcorsi/models.py` (classe `Course` ~riga 379; nuova classe `CourseCodeFailure` in fondo alla sezione corsi)
- Create: `migrations/versions/a7c3e9d1b4f6_iscrizione_diretta_codice.py` (revision `"a7c3e9d1b4f6"`, down_revision `"f3b9c1d7e5a2"`)
- Test: `tests/test_migrations.py`

**Interfaces:**
- Produces: `Course.self_enrollment_enabled: bool` (`db.Boolean, nullable=False, default=False, server_default=sa.false()`); `CourseCodeFailure` (`__tablename__ = "course_code_failures"`, `id` String(36) pk `default=new_uuid`, `scope` String(8), `subject` String(64), `failures` Integer default 0, `last_failure_at` DateTime(tz), `blocked_until` DateTime(tz) nullable, `UniqueConstraint("scope", "subject")`, `CheckConstraint("scope IN ('user', 'ip')")`).

- [ ] **Step 1: Test** `test_self_enrollment_migration_defaults_false` in `tests/test_migrations.py`: migra a `"f3b9c1d7e5a2"`, inserisce un corso con `_insert(connection, "courses", ...)` (più le righe padre necessarie, come nei test esistenti), migra a `"head"`, poi asserisce `SELECT self_enrollment_enabled FROM courses` → `0` e che `course_code_failures` esista con indice unico su (`scope`, `subject`) (`PRAGMA index_list`).
- [ ] **Step 2:** `pytest tests/test_migrations.py -v` → FAIL (colonna assente).
- [ ] **Step 3:** Aggiungi colonna e modello; migrazione idempotente nello stile di `f3b9c1d7e5a2` (ispeziona colonne/tabelle prima di aggiungerle), `batch_alter_table("courses")` per la colonna, `create_table` per la nuova tabella; `downgrade` rimuove entrambe.
- [ ] **Step 4:** `pytest tests/test_migrations.py -v` → PASS; `pytest -q` → tutto verde.
- [ ] **Step 5:** Commit `Aggiungi flag iscrizione diretta e tabella errori codice corso`.

### Task 2: Checkbox nel form corso, salvataggio, dettaglio

**Files:**
- Modify: `mcorsi/courses/forms.py` (`CourseForm`), `mcorsi/courses/routes.py:51` (`_course_form_data`), `mcorsi/services/courses.py` (`create_course`, `update_course`), `mcorsi/templates/courses/form.html`, `mcorsi/templates/courses/detail.html:32`
- Test: `tests/test_course_ux.py`

**Interfaces:**
- Consumes: `Course.self_enrollment_enabled` (Task 1).
- Produces: `data["self_enrollment_enabled"]` letto con `bool(data.get("self_enrollment_enabled", False))` da `create_course`/`update_course` (i chiamanti esistenti senza la chiave restano validi). `course.updated` include `"self_enrollment_enabled"` in `before` e `after` (copre l'audit della modifica del flag: nessun evento separato).

- [ ] **Step 1: Test** in `tests/test_course_ux.py`:
  - `test_course_form_saves_self_enrollment_flag`: POST di creazione con `self_enrollment_enabled="y"` → `course.self_enrollment_enabled is True`; POST di modifica senza il campo → `False`; l'evento `course.updated` ha `detail["before"]["self_enrollment_enabled"] is True` e `detail["after"]["self_enrollment_enabled"] is False`.
  - `test_course_detail_shows_self_enrollment_state`: GET dettaglio contiene "Iscrizione diretta con codice" e "attiva" quando acceso, "non attiva" quando spento.
- [ ] **Step 2:** `pytest tests/test_course_ux.py -v` → FAIL.
- [ ] **Step 3:** `BooleanField("Iscrizione diretta con codice", default=False)`; in `form.html` render con hint "Chi inserisce il codice viene iscritto subito, finché il corso non è chiuso." (accanto a `certificate_validity_months`); nel riquadro "Codice di ammissione" di `detail.html` una riga "Iscrizione diretta con codice: attiva/non attiva" e testo adeguato ("…per iscriversi subito" vs "…per chiedere l'accesso").
- [ ] **Step 4:** `pytest -q` → PASS.
- [ ] **Step 5:** Commit `Aggiungi opzione iscrizione diretta al form del corso`.

### Task 3: Throttle dei codici errati

**Files:**
- Create: `mcorsi/services/course_code_throttle.py`
- Test: `tests/test_course_code_throttle.py`

**Interfaces:**
- Consumes: `CourseCodeFailure` (Task 1), `record_event`, `_aware` da `mcorsi/services/otp.py`.
- Produces:
  - `class CourseCodeThrottled(Exception)` con attributo `retry_after: int` e `str(exc) == f"Troppi tentativi: riprova tra {retry_after} secondi."`
  - `delay_for_failures(failures: int) -> int`
  - `check_course_code_allowed(user_id: str, ip: str, *, now: datetime | None = None) -> None` — solleva `CourseCodeThrottled` con il blocco residuo più lungo fra le due righe (secondi arrotondati per eccesso, minimo 1).
  - `record_course_code_failure(user: User, ip: str, *, now: datetime | None = None) -> int` — incrementa entrambe le righe (`scope="user"`, subject `user.id`; `scope="ip"`, subject `ip`), imposta `last_failure_at=now`, `blocked_until=now + delay` (o `None` se 0), registra `course_code.failed` con `actor=user`, `detail={"ip": ip, "failures": <max dei due conteggi>}`, ritorna quel massimo. Non fa commit.
  - `reset_course_code_failures(user_id: str, ip: str) -> None` — elimina le due righe. Non fa commit.
  - Regola di scadenza (in entrambe le funzioni di lettura/scrittura): riga con `last_failure_at` più vecchio di 1 ora → trattata come assente (eliminata alla lettura).

- [ ] **Step 1: Test** (con `now` esplicito, nessuno sleep; utenti creati come in `_admin` di `test_portal_otp.py` ma con ruolo participant):
  - `test_delay_sequence`: `[delay_for_failures(n) for n in (1,2,3,4,10,20)] == [0, 2, 4, 8, 256, 300]`
  - `test_first_failure_does_not_block`: 1 errore → `check_course_code_allowed` non solleva.
  - `test_second_and_third_failure_block_2_and_4_seconds`: dopo il 2° errore a `t0`, check a `t0+1s` solleva con `retry_after == 1`, a `t0+2s` non solleva; dopo il 3° errore a `t0+2s`, check a `t0+3s` → `retry_after == 3`.
  - `test_delay_capped_at_300_seconds`: 12 errori → `blocked_until - last_failure_at == timedelta(seconds=300)`.
  - `test_ip_block_applies_to_other_users`: utente A sbaglia 3 volte da `"10.0.0.1"`; utente B dallo stesso IP → `CourseCodeThrottled`; utente B da `"10.0.0.2"` → ok.
  - `test_reset_clears_user_and_ip`: dopo reset non solleva e non ci sono righe.
  - `test_failures_expire_after_one_hour`: 5 errori a `t0`; `record_course_code_failure(..., now=t0+61min)` ritorna `1`.
  - `test_failure_audit_never_contains_code`: l'evento `course_code.failed` ha `detail == {"ip": "10.0.0.1", "failures": 1}`.
- [ ] **Step 2:** `pytest tests/test_course_code_throttle.py -v` → FAIL (modulo assente).
- [ ] **Step 3:** Implementa il modulo con le firme sopra; `now` di default `utc_now()`; confronti con `_aware(...)` perché SQLite restituisce datetime naive.
- [ ] **Step 4:** `pytest tests/test_course_code_throttle.py -v` → PASS.
- [ ] **Step 5:** Commit `Aggiungi ritardo progressivo per codici corso errati`.

### Task 4: Servizio `self_enroll`

**Files:**
- Modify: `mcorsi/services/courses.py`
- Test: `tests/test_self_enrollment.py` (nuovo)

**Interfaces:**
- Consumes: `request_admission`, `decide_admission`, `record_event`, `Enrollment`, `AdmissionRequest`.
- Produces:
  - `SELF_ENROLLMENT_STATUSES = ("open", "in_progress")`
  - `accepts_self_enrollment(course: Course) -> bool` — flag acceso e stato in `SELF_ENROLLMENT_STATUSES`.
  - `self_enrollment_problem(course: Course, participant: User) -> str | None` — `"Sei già iscritto a questo corso."` se esiste `Enrollment`; il messaggio di rifiuto del referente se l'`AdmissionRequest` è `rejected`; altrimenti `None`. (Usata anche dal portale prima di mostrare la conferma.)
  - `self_enroll(course: Course, participant: User) -> Enrollment` — `CourseOperationError("Codice non valido o corso non aperto alle richieste.")` se `not accepts_self_enrollment(course)`; `CourseOperationError(problem)` se `self_enrollment_problem` restituisce un testo; richiesta `pending` esistente → `decide_admission(admission, actor=participant, approve=True, decision_message="Iscrizione diretta con codice")`; nessuna richiesta → `request_admission(course, participant, actor=participant)` poi la stessa `decide_admission`; poi `record_event("enrollment.self_enrolled", actor=participant, target_type="course", target_id=course.id, detail={"participant": participant.id})`. Non fa commit.

- [ ] **Step 1: Test** (parametrizzati dove indicato):
  - `test_self_enroll_creates_enrollment` parametrizzato su `open`, `in_progress`: `Enrollment` esiste, `AdmissionRequest.status == "approved"`, `decision_message == "Iscrizione diretta con codice"`, evento `enrollment.self_enrolled` presente.
  - `test_self_enroll_rejects_closed_states` parametrizzato su `draft`, `completed`, `canceled`, `archived` (e su `open` con flag spento): `CourseOperationError` con il messaggio generico, nessuna `Enrollment`.
  - `test_self_enroll_approves_pending_request`: richiesta `pending` preesistente → stessa riga approvata, una sola `AdmissionRequest`.
  - `test_self_enroll_already_enrolled_no_duplicate`: seconda chiamata → `CourseOperationError("Sei già iscritto a questo corso.")`, `Enrollment.query.count() == 1`.
  - `test_self_enroll_rejected_request_blocks`: richiesta `rejected` → messaggio "La tua richiesta per questo corso è stata respinta: contatta il referente.", nessuna `Enrollment`.
  - Imposta lo stato del corso direttamente sul modello (`course.status = ...`) dopo `create_course`, senza passare per le transizioni.
- [ ] **Step 2:** `pytest tests/test_self_enrollment.py -v` → FAIL.
- [ ] **Step 3:** Implementa le funzioni sopra in `mcorsi/services/courses.py`.
- [ ] **Step 4:** `pytest tests/test_self_enrollment.py -v` → PASS.
- [ ] **Step 5:** Commit `Aggiungi servizio di iscrizione diretta al corso`.

### Task 5: Portale — inserimento codice e pagina di conferma

**Files:**
- Modify: `mcorsi/portal/routes.py` (`profile`, `add_admission`, nuova `confirm_enrollment`), `mcorsi/templates/portal/profile.html`
- Test: `tests/test_portal_self_enrollment.py` (nuovo; riusa `_admin`, `_request_and_verify`, `_profile_payload` importandoli da `tests.test_portal_otp` o copiandoli in un helper condiviso)

**Interfaces:**
- Consumes: Task 3 (`check_course_code_allowed`, `record_course_code_failure`, `reset_course_code_failures`, `CourseCodeThrottled`), Task 4 (`accepts_self_enrollment`, `self_enrollment_problem`, `self_enroll`).
- Produces:
  - `_apply_profile_form(form: ParticipantProfileForm) -> bool` — estratta da `profile()`: tutto il salvataggio (P.IVA, azienda, campi utente/profilo, `request_company_association`, `profile_completed=True`, audit) **senza** commit/flash/redirect; ritorna `False` se ha aggiunto errori al form. `profile()` la usa invariando il comportamento.
  - Route `portal.confirm_enrollment`, GET/POST `/participant/enroll/confirm`, `@participant_required`, render di `portal/profile.html` con `enrolling_course=course` (intestazione "Stai per iscriverti a: <titolo>", submit con label "Conferma e iscriviti").
  - `profile.html` accetta anche `course_code_form` opzionale: al primo accesso, senza corso in sessione, mostra sopra il form il riquadro codice (stesso markup della dashboard).

**Comportamento di `add_admission` (ordine):**
1. Form non valido → flash "Controlla il codice del corso." (nessun conteggio).
2. `check_course_code_allowed(current_user.id, request.remote_addr or "")` → su `CourseCodeThrottled` flash `str(exc)` e redirect, **prima** di qualsiasi query sul corso.
3. Lookup con `normalize_identifier`. Corso valido per il ramo pertinente = `accepts_self_enrollment(course)` oppure (`not course.self_enrollment_enabled` e `status == "open"`). Altrimenti → `record_course_code_failure`, commit, flash messaggio generico.
4. Codice valido → `reset_course_code_failures`.
   - Flag acceso: se `self_enrollment_problem` → flash quel testo; altrimenti `session["pending_self_enrollment"] = course.id` e redirect a `portal.confirm_enrollment`.
   - Flag spento: profilo incompleto → flash "Completa il profilo prima di chiedere l'ammissione." e redirect a `portal.profile`; altrimenti `request_admission` come oggi.
5. Il redirect di ritorno è `portal.dashboard` se il profilo è completo, altrimenti `portal.profile`. `add_admission` non richiede più il profilo completo.

**Comportamento di `confirm_enrollment`:**
- Nessuna chiave in sessione o corso inesistente → redirect a `portal.dashboard` (che a sua volta manda a `profile` se incompleto).
- GET e POST ricontrollano `accepts_self_enrollment(course)`: se falso → `session.pop`, flash messaggio generico, redirect; nulla viene salvato.
- POST valido: `_apply_profile_form(form)`; se `False` → rimostra la pagina (sessione intatta). Poi `self_enroll(course, current_user)`; `CourseOperationError` → `db.session.rollback()`, `session.pop`, flash `str(exc)`, redirect. Successo → commit unico, `session.pop("pending_self_enrollment")`, flash "Iscrizione completata: puoi svolgere il questionario.", redirect a `portal.dashboard`.

- [ ] **Step 1: Test** in `tests/test_portal_self_enrollment.py`:
  - `test_incomplete_profile_code_then_confirm_enrolls`: OTP → profilo incompleto → GET `/participant/profile` contiene il riquadro codice → POST `/participant/admissions` col codice (flag acceso, `open`) → 302 a `/participant/enroll/confirm`; GET contiene "Stai per iscriverti a: Radioprotezione" e "Conferma e iscriviti"; POST `_profile_payload()` → 302 a `/participant`, `user.profile_completed`, una `Enrollment`, flash finale, chiave di sessione assente.
  - `test_self_enroll_accepts_lowercase_code`: codice inviato `.lower()` con uno spazio interno → redirect alla conferma.
  - `test_flag_off_keeps_pending_request` (profilo completo, `open`) → `AdmissionRequest.status == "pending"`, nessuna `Enrollment`; `in_progress` con flag spento → messaggio generico.
  - `test_confirm_rechecks_course_state`: codice in sessione, poi corso → `completed` (e in un secondo caso flag spento) → POST conferma: nessuna `Enrollment`, messaggio generico, `profile_completed` invariato.
  - `test_confirm_does_not_overwrite_verified_company`: azienda `verified` con P.IVA nota e `business_name="Originale Srl"`; conferma con quella P.IVA e `company_business_name="Hack Srl"` → `business_name == "Originale Srl"`.
  - `test_confirm_invalid_vat_keeps_pending_course`: POST con `vat_number="123"` → 200, pagina con errore e intestazione corso, nessuna `Enrollment`, chiave di sessione presente.
  - `test_profile_save_does_not_enroll_with_pending_code`: codice in sessione, POST su `/participant/profile` → nessuna `Enrollment`.
  - `test_wrong_codes_throttle_and_audit`: 2 codici errati → il 3° tentativo (anche con codice valido: `test_valid_code_rejected_while_blocked`) riceve "Troppi tentativi: riprova tra 2 secondi." senza creare richieste; nessun `AuditEvent` ha il codice digitato nel `detail`.
  - `test_already_enrolled_code_shows_message`: già iscritto → flash "Sei già iscritto a questo corso.", nessun redirect alla conferma.
- [ ] **Step 2:** `pytest tests/test_portal_self_enrollment.py -v` → FAIL.
- [ ] **Step 3:** Estrai `_apply_profile_form`, riscrivi `add_admission`, aggiungi `confirm_enrollment` e le varianti di `profile.html`.
- [ ] **Step 4:** `pytest -q` → tutto PASS (incluso `test_otp_profile_company_and_course_request` invariato).
- [ ] **Step 5:** Commit `Aggiungi iscrizione diretta con codice nel portale partecipante`.

### Task 6: Dashboard — riquadro codice in evidenza

**Files:**
- Modify: `mcorsi/portal/routes.py` (`dashboard`), `mcorsi/templates/portal/dashboard.html`, `mcorsi/static/css/app.css` (accanto a `.join-panel`, riga ~173)
- Test: `tests/test_portal_self_enrollment.py`

**Interfaces:**
- Produces: variabile di template `highlight_code_box: bool` = nessuna `Enrollment` del partecipante su corsi con stato in `("open", "in_progress")` **e** nessuna `AdmissionRequest` `pending`.

- [ ] **Step 1: Test** `test_dashboard_highlights_code_box_without_active_courses`: partecipante con profilo completo e nessun corso → HTML contiene `join-panel-highlight` e "Inserisci il codice del corso" prima di "Corsi e richieste"; dopo un'iscrizione diretta a un corso `open` → `join-panel-highlight` assente e il riquadro è nella posizione attuale (dopo il blocco azienda).
- [ ] **Step 2:** `pytest tests/test_portal_self_enrollment.py -k dashboard -v` → FAIL.
- [ ] **Step 3:** Calcola il flag in `dashboard()`; nel template, se vero, renderizza il riquadro subito dopo l'hero con classe aggiuntiva `join-panel-highlight` e titolo "Inserisci il codice del corso", altrimenti nella posizione di oggi (mai due volte); stile in evidenza (bordo/ombra) in `app.css`.
- [ ] **Step 4:** `pytest -q` → PASS.
- [ ] **Step 5:** Commit `Evidenzia il codice corso per chi non ha corsi attivi`.
