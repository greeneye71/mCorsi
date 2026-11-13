# Corsi: interventi rapidi di usabilità (fase 1) — Piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ridurre i passaggi e gli attriti nella creazione e gestione di un corso da parte dell'operatore, senza cambiare il modello dati.

**Architecture:** Interventi mirati su blueprint `courses`, `documents`, `participants` e `main` e sui relativi template Jinja. La logica nuova va nei service (`mcorsi/services/courses.py`, `mcorsi/services/participants.py`); le route restano sottili. Nessuna migrazione Alembic.

**Tech Stack:** Python, Flask, Flask-WTF/WTForms, SQLAlchemy, Flask-Login, Jinja2, pytest.

**Spec:** Nessun documento di spec separato. La fonte è l'analisi UX condivisa in sessione il 13/11/2026 (fase 1 "quick wins"). Restano fuori, per piani successivi: checklist "Pronto al via", wizard di creazione, iscrizione massiva da elenco/CSV, modello di attestato predefinito, corsi modello, editor questionari a pagina singola.

## Global Constraints

- Tutti i testi dell'interfaccia in italiano, tono coerente con quelli esistenti (es. "Partecipante creato.").
- Nessuna nuova dipendenza, nessuna migrazione del DB.
- Ogni azione che modifica dati chiama `record_event(...)` come fa già il codice circostante.
- Le route POST nuove usano `@staff_required` e, dove indicato, `can_review_course(course)` con `abort(403)`.
- Redirect dopo POST sempre verso `courses.detail` del corso coinvolto, salvo dove indicato.
- Test in `tests/test_course_ux.py` (nuovo), riusando gli helper `_make_user`, `_login`, `_course_payload` copiandoli o importandoli da `tests/test_courses_and_participants.py`. In test `WTF_CSRF_ENABLED = False`.
- Suite completa verde a fine di ogni task: `python -m pytest -q`.

## Review Focus

1. Utente senza ruolo staff (partecipante) che invia POST a `/courses/<id>/admissions` o a una decisione: 403, nessuna iscrizione creata. → test in Task 4.
2. Cambio di stato non ammesso (es. `completed` → `open`, oppure POST ripetuto): nessuna modifica, messaggio d'errore, nessun 500. → test in Task 1.
3. Email già presente come operatore/admin quando si crea il partecipante dalla pagina corso: nessun utente duplicato, nessun ruolo aggiunto in silenzio. → test in Task 3.
4. "Genera tutti gli attestati" con alcuni iscritti non pronti o già con attestato: genera solo i pronti, non rigenera, riporta i conteggi. → test in Task 6.
5. Parametro `next` esterno (`https://evil.example`, `//evil.example`) dopo la creazione partecipante: ignorato, redirect all'elenco. → test in Task 7.

---

### Task 1: Form corso ripulito e stato gestito con pulsanti

Lo stato esce dal form (creazione e modifica). Un corso nuovo nasce sempre in bozza; lo stato si cambia con pulsanti nella pagina del corso.

**Files:**
- Modify: `mcorsi/courses/forms.py` (togliere `status` da `CourseForm`; aggiungere `CourseStatusForm`)
- Modify: `mcorsi/courses/routes.py` (`_course_form_data`, `create`, `edit`, `detail`, nuova route `change_status`)
- Modify: `mcorsi/services/courses.py` (`create_course`, `update_course`, nuova `change_course_status`)
- Create: `mcorsi/templates/courses/_macros.html`
- Modify: `mcorsi/templates/courses/form.html`, `mcorsi/templates/courses/detail.html`
- Modify: `tests/test_courses_and_participants.py` (test che si affidano a `status` nel POST di creazione)
- Test: `tests/test_course_ux.py`

**Interfaces:**
- Produces:
  - `COURSE_STATUS_TRANSITIONS: dict[str, tuple[str, ...]]` in `mcorsi/services/courses.py`:
    `draft → (open, canceled)`, `open → (in_progress, canceled)`, `in_progress → (completed, canceled)`, `completed → (archived,)`, `canceled → ()`, `archived → ()`.
  - `change_course_status(course: Course, *, actor: User, new_status: str) -> Course` — solleva `CourseOperationError("Passaggio di stato non consentito.")` se la transizione non è in tabella; registra `record_event("course.status_changed", ..., detail={"from": ..., "to": ...})`.
  - `create_course` usa `data.get("status", "draft")`; `update_course` cambia `course.status` solo se `"status" in data`.
  - Route `POST /courses/<course_id>/status` → endpoint `courses.change_status`, campo form `status`. `@staff_required`.
  - Macro Jinja `render_field(field, wide=False)` in `courses/_macros.html`: label con ` *` se `field.flags.required`, widget, errori `<p class="field-error">`.
  - Etichette pulsanti (mappa nel template o passata dalla route): `open` "Apri iscrizioni", `in_progress` "Avvia corso", `completed` "Concludi corso", `archived` "Archivia", `canceled` "Annulla corso".

- [ ] **Step 1: Write the failing tests** in `tests/test_course_ux.py`

```python
def test_new_course_is_always_draft_and_form_has_no_status(app, client):
    admin_id = _make_user(app, "admin@example.it", "admin")
    _login(client, "admin@example.it")
    page = client.get("/courses/new").get_data(as_text=True)
    assert 'name="status"' not in page
    assert "La struttura dati supporta" not in page
    assert 'href="/courses"' in page          # Annulla anche in creazione
    assert "*" in page                         # asterischi obbligatori
    client.post("/courses/new", data=_course_payload(admin_id) | {"status": "open"})
    with app.app_context():
        assert Course.query.one().status == "draft"

def test_status_buttons_follow_allowed_transitions(app, client):
    # crea corso in bozza via POST, poi:
    # POST /courses/<id>/status status=open        -> status "open"
    # POST /courses/<id>/status status=completed   -> resta "open", flash "Passaggio di stato non consentito."
    # POST status=in_progress, poi status=completed -> "completed"
    # GET detail su corso "open" contiene "Avvia corso" e non "Apri iscrizioni"

def test_edit_does_not_change_status(app, client):
    # corso "open"; POST /courses/<id>/edit con payload completo + status=draft -> resta "open"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_course_ux.py -v`
Expected: FAIL (`name="status"` presente, route `/status` 404)

- [ ] **Step 3: Implement**
  - `forms.py`: rimuovere `status` da `CourseForm`; `CourseStatusForm(FlaskForm)` con `status = HiddenField(validators=[DataRequired()])`.
  - `routes.py`: `_course_form_data` senza `status`; `detail` passa `status_form=CourseStatusForm()` e `next_statuses=COURSE_STATUS_TRANSITIONS[course.status]`; `change_status` chiama il service, `commit`, flash `"Stato aggiornato: {etichetta}."` oppure l'errore con `rollback`.
  - `form.html`: usare `render_field` su tutti i campi; togliere la riga sullo stato e la frase "La struttura dati supporta già più sedute…"; "Annulla" sempre visibile (`courses.detail` in modifica, `courses.index` in creazione).
  - `detail.html`: nell'intestazione, accanto a Duplica/Modifica, un form POST per ogni stato in `next_statuses`; "Annulla corso" come pulsante secondario.
  - Test esistenti: dove il flusso richiede un corso aperto dopo `POST /courses/new`, aggiungere `client.post(f"/courses/{id}/status", data={"status": "open"})`. I test che usano `create_course(...)` direttamente con `"status": "open"` non cambiano.

- [ ] **Step 4: Run tests**

Run: `python -m pytest -q`
Expected: tutto PASS

- [ ] **Step 5: Commit**

```bash
git add mcorsi/courses mcorsi/services/courses.py mcorsi/templates/courses tests
git commit -m "Gestisci lo stato del corso con pulsanti e ripulisci il form"
```

---

### Task 2: Iscrizione diretta da parte dello staff

Oggi "Registra richiesta" crea una richiesta in attesa che lo stesso operatore deve poi approvare. Diventa un'iscrizione immediata.

**Files:**
- Modify: `mcorsi/services/courses.py` (nuova `enroll_participant`)
- Modify: `mcorsi/courses/routes.py:164-185` (`add_admission`)
- Modify: `mcorsi/courses/forms.py` (`AdmissionAddForm.submit` → "Iscrivi")
- Modify: `mcorsi/templates/courses/detail.html` (titolo e testo del pannello)
- Modify: `tests/test_courses_and_participants.py` (`test_full_operator_flow_and_clean_duplication`: dopo il POST ad `/admissions` l'iscrizione esiste già; togliere il passo di approvazione o puntarlo a una richiesta creata dal portale)
- Test: `tests/test_course_ux.py`

**Interfaces:**
- Consumes: `request_admission`, `decide_admission` (esistenti).
- Produces: `enroll_participant(course: Course, participant: User, *, actor: User) -> Enrollment`
  - nessuna richiesta → `request_admission` + `decide_admission(approve=True)`;
  - richiesta `pending` → la approva;
  - richiesta `approved` → `CourseOperationError("Il partecipante è già iscritto.")`;
  - richiesta `rejected` → `CourseOperationError("La richiesta di questo partecipante è stata rifiutata.")`.
  - Restituisce l'`Enrollment` creato (`db.session.flush()` prima di restituirlo).

- [ ] **Step 1: Write the failing tests**

```python
def test_staff_add_enrolls_immediately(app, client):
    # admin, partecipante esistente, corso aperto
    # POST /courses/<id>/admissions email=persona@example.it
    with app.app_context():
        assert AdmissionRequest.query.one().status == "approved"
        assert Enrollment.query.count() == 1

def test_staff_add_approves_pending_portal_request(app, client):
    # request_admission(course, participant, actor=participant) poi POST staff
    # -> stessa AdmissionRequest "approved", 1 Enrollment

def test_staff_add_twice_reports_already_enrolled(app, client):
    # secondo POST -> flash "Il partecipante è già iscritto.", Enrollment.count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_course_ux.py -k staff_add -v`
Expected: FAIL (status "pending")

- [ ] **Step 3: Implement** `enroll_participant`; `add_admission` lo chiama al posto di `request_admission`; flash `"{display_name} iscritto al corso."`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest -q`
Expected: tutto PASS

- [ ] **Step 5: Commit**

```bash
git add mcorsi tests
git commit -m "Iscrivi subito i partecipanti aggiunti dallo staff"
```

---

### Task 3: Creare il partecipante dalla pagina del corso

Se l'email non esiste, oggi l'operatore deve uscire, creare il partecipante in anagrafica e tornare. Il form di iscrizione accetta anche nome e cognome e crea il partecipante al volo.

**Files:**
- Modify: `mcorsi/services/participants.py` (nuova `create_minimal_participant`)
- Modify: `mcorsi/courses/forms.py` (`AdmissionAddForm`: `first_name`, `last_name` Optional, max 120)
- Modify: `mcorsi/courses/routes.py` (`add_admission`)
- Modify: `mcorsi/templates/courses/detail.html`
- Test: `tests/test_course_ux.py`

**Interfaces:**
- Consumes: `enroll_participant` (Task 2), `ensure_roles` da `mcorsi.cli`, `normalize_email`.
- Produces: `create_minimal_participant(*, email: str, first_name: str, last_name: str, actor: User) -> User`
  - crea `User(is_active=True, profile_completed=False)` con ruolo `participant` e `ParticipantProfile()` vuoto;
  - `record_event("participant.created", ..., detail={"email": ..., "source": "course_page"})`.

Comportamento della route con email non trovata:
- nome e cognome presenti → crea, iscrive, flash `"{nome} creato e iscritto. Completa l'anagrafica per poter emettere l'attestato."` con link a `participants.edit` (flash testuale; il link è nel pannello iscritti, vedi sotto);
- nome o cognome mancanti → flash `"Email non trovata: indica nome e cognome per creare il partecipante."`.

Con email di un utente esistente senza ruolo `participant` → flash `"Questa email appartiene a un utente dello staff."`, nessuna modifica.

Nel pannello iscritti, accanto a "Manca: anagrafica incompleta", aggiungere link "Completa" a `participants.edit` con `next` alla pagina corso (usato dal Task 7).

- [ ] **Step 1: Write the failing tests**

```python
def test_add_unknown_email_with_names_creates_and_enrolls(app, client):
    # POST /courses/<id>/admissions email=nuovo@example.it first_name=Mario last_name=Rossi
    with app.app_context():
        user = User.query.filter_by(email="nuovo@example.it").one()
        assert user.has_role("participant") and not user.profile_completed
        assert Enrollment.query.filter_by(participant_user_id=user.id).count() == 1

def test_add_unknown_email_without_names_asks_for_them(app, client):
    # follow_redirects=True -> "indica nome e cognome" nel testo; User non creato

def test_add_staff_email_is_refused(app, client):
    # email di un operatore -> "appartiene a un utente dello staff"; ruoli invariati; nessuna Enrollment
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_course_ux.py -k add_ -v`
Expected: FAIL

- [ ] **Step 3: Implement** service, campi form, ramo nella route, due campi nel template accanto all'email con nota "Solo se il partecipante non è ancora in anagrafica".

- [ ] **Step 4: Run tests**

Run: `python -m pytest -q`
Expected: tutto PASS

- [ ] **Step 5: Commit**

```bash
git add mcorsi tests
git commit -m "Crea il partecipante direttamente dalla pagina del corso"
```

---

### Task 4: Ogni operatore può iscrivere e decidere le richieste

Decisione del 13/11/2026: qualsiasi utente staff (admin o operatore) può iscrivere partecipanti e approvare/rifiutare richieste su qualsiasi corso. Il referente resta un'informazione del corso, non un vincolo di permesso. Questo supera il rilievo dell'audit (`AUDIT-SICUREZZA.md:407-409`), che chiedeva di limitare `add_admission` al referente: la regola ora è uniforme ma più ampia, ed è voluta.

**Files:**
- Modify: `mcorsi/services/permissions.py:67-68` (`can_review_course`)
- Modify: `tests/test_courses_and_participants.py` (`test_only_referent_or_admin_can_decide`, `test_unrelated_operator_cannot_add_an_admission`)
- Modify: `AUDIT-SICUREZZA.md` (nota sotto il rilievo di riga 407: regola cambiata per decisione del committente il 13/11/2026)
- Test: `tests/test_course_ux.py`

**Interfaces:**
- Produces: `can_review_course(course) -> bool` restituisce `True` se `current_user` ha ruolo `admin` o `operator`. Le route `add_admission` e `_decide` continuano a chiamarla; `detail()` continua a passare `may_review`.

- [ ] **Step 1: Write the failing tests**

```python
def test_any_operator_can_enroll_and_decide(app, client):
    # corso con referente operatore A; login operatore B
    # POST /courses/<id>/admissions email=persona@example.it -> 302, Enrollment.count() == 1
    # richiesta pending creata dal portale per un secondo partecipante;
    # B POST approve -> status "approved"

def test_participant_cannot_enroll_or_decide(app, client):
    # login partecipante; POST /courses/<id>/admissions -> 403; POST approve -> 403
    # Enrollment.count() invariato
```

Rinominare e invertire i due test esistenti: `test_any_operator_can_decide` (atteso 302 e decisione registrata) e `test_any_operator_can_add_an_admission` (atteso 302 e iscrizione creata).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_course_ux.py -k "any_operator or participant_cannot" -v`
Expected: FAIL (403 per l'operatore B)

- [ ] **Step 3: Implement** `can_review_course`: `return current_user.has_role("admin") or current_user.has_role("operator")`. Il parametro `course` resta per non cambiare i chiamanti.

- [ ] **Step 4: Run tests** — `python -m pytest -q`, tutto PASS.

- [ ] **Step 5: Commit**

```bash
git add mcorsi/services/permissions.py tests AUDIT-SICUREZZA.md
git commit -m "Consenti a ogni operatore di gestire le iscrizioni dei corsi"
```

---

### Task 5: Elenco corsi: ordine, ricerca, filtri, Duplica

**Files:**
- Modify: `mcorsi/courses/routes.py:56-60` (`index`), `duplicate` (default data)
- Modify: `mcorsi/templates/courses/index.html`
- Modify: `mcorsi/templates/main/dashboard.html:16`
- Test: `tests/test_course_ux.py`

**Interfaces:**
- Produces: `GET /courses` accetta query `q` (sottostringa del titolo o codice, case-insensitive), `status` (uno di `COURSE_STATUS_CHOICES`, altrimenti ignorato), `pending=1` (solo corsi con almeno una `AdmissionRequest` `pending`).
- Ordine: data della prima seduta decrescente (outer join su `CourseSession` con `sequence == 1`), corsi senza seduta in fondo, poi `created_at` decrescente.
- Dashboard: la card "Richieste in attesa" ha link "Vedi" a `url_for('courses.index', pending=1)`.
- `duplicate` GET: `session_date` precompilata con `date.today()` se il form non è inviato.

- [ ] **Step 1: Write the failing tests**

```python
def test_course_list_search_filter_and_order(app, client):
    # tre corsi via create_course: "Antincendio" 2026-03-01 open, "Primo soccorso" 2026-06-01 draft,
    # "Antincendio avanzato" 2026-09-01 completed
    page = client.get("/courses").get_data(as_text=True)
    assert page.index("Antincendio avanzato") < page.index("Primo soccorso") < page.index(">Antincendio<")
    page = client.get("/courses?q=antinc").get_data(as_text=True)
    assert "Primo soccorso" not in page
    page = client.get("/courses?status=draft").get_data(as_text=True)
    assert "Primo soccorso" in page and "Antincendio" not in page
    assert client.get("/courses?status=xyz").status_code == 200
    assert "/duplicate" in client.get("/courses").get_data(as_text=True)

def test_pending_filter_and_dashboard_link(app, client):
    # una richiesta pending su un corso solo
    # /courses?pending=1 mostra solo quel corso; dashboard contiene "/courses?pending=1"
```

L'asserzione d'ordine sul titolo esatto va adattata al markup reale del link del titolo; l'importante è l'ordine per data.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_course_ux.py -k "course_list or pending_filter" -v`
Expected: FAIL

- [ ] **Step 3: Implement** query in `index`; barra di ricerca GET (campo `q`, select `status` con "Tutti", pulsante "Cerca", link "Azzera") in testa a `index.html`; pulsante "Duplica" su ogni card verso `courses.duplicate`; link nella dashboard; default data in `duplicate`.

- [ ] **Step 4: Run tests** — `python -m pytest -q`, tutto PASS.

- [ ] **Step 5: Commit**

```bash
git add mcorsi tests
git commit -m "Aggiungi ricerca, filtri e Duplica all'elenco corsi"
```

---

### Task 6: Azioni di fine corso in blocco

**Files:**
- Modify: `mcorsi/documents/routes.py` (due route nuove dopo `create_certificate`)
- Modify: `mcorsi/templates/courses/detail.html` (pulsanti sopra la tabella iscritti)
- Test: `tests/test_course_ux.py`

**Interfaces:**
- Consumes: `readiness(enrollment) -> tuple[bool, list[str]]`, `generate_certificate(enrollment, *, actor) -> Certificate`, `CertificateError` (già importati in `documents/routes.py`).
- Produces:
  - `POST /documents/courses/<course_id>/attendance/all` → `documents.mark_all_attended`: ogni `Enrollment` del corso con `attendance_status == "pending"` diventa `"attended"`; gli `absent` restano. Un `record_event("enrollment.attendance_updated", ...)` per iscrizione. Flash `"{n} presenze confermate."`.
  - `POST /documents/courses/<course_id>/certificates/all` → `documents.generate_all_certificates`: per ogni iscrizione senza `certificate` e con `readiness` ok chiama `generate_certificate`; un `CertificateError` su una iscrizione non blocca le altre (savepoint `db.session.begin_nested()` per ciascuna). Flash `"{generati} attestati generati, {saltati} non pronti."`.
  - Entrambe `@staff_required`, redirect a `courses.detail`.
- Template: "Tutti presenti" visibile se esiste almeno un `pending`; "Genera tutti gli attestati" visibile se `course.status == "completed"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_mark_all_attended_keeps_absent(app, client):
    # tre iscrizioni: pending, pending, absent -> attended, attended, absent

def test_generate_all_only_ready_and_not_already_issued(app, client, monkeypatch):
    calls = []
    def fake_generate(enrollment, *, actor):
        calls.append(enrollment.id)
        return Certificate(...)   # o un oggetto con certificate_number e id
    monkeypatch.setattr("mcorsi.documents.routes.generate_certificate", fake_generate)
    monkeypatch.setattr("mcorsi.documents.routes.readiness", lambda e: (e.id in ready_ids, []))
    # iscrizioni: pronta, pronta con attestato già presente, non pronta
    assert calls == [id_pronta]
```

Se `readiness` non è importato per nome in `documents/routes.py`, importarlo così (`from ..services.certificates import readiness`) per poterlo sostituire nel test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_course_ux.py -k "all_attended or generate_all" -v`
Expected: FAIL (404)

- [ ] **Step 3: Implement** le due route e i pulsanti.

- [ ] **Step 4: Run tests** — `python -m pytest -q`, tutto PASS.

- [ ] **Step 5: Commit**

```bash
git add mcorsi/documents/routes.py mcorsi/templates/courses/detail.html tests/test_course_ux.py
git commit -m "Aggiungi presenze e attestati in blocco a fine corso"
```

---

### Task 7: Ritorno al corso dopo la modifica dell'anagrafica

**Files:**
- Modify: `mcorsi/participants/routes.py:105-167` (`create`, `edit`)
- Create: `mcorsi/services/navigation.py`
- Modify: `mcorsi/templates/participants/form.html` (campo hidden `next`, "Annulla" verso `next`)
- Test: `tests/test_course_ux.py`

**Interfaces:**
- Produces: `safe_next(value: str | None, fallback: str) -> str` in `mcorsi/services/navigation.py` — accetta solo percorsi che iniziano con `/` e non con `//` né contengono `\`; altrimenti `fallback`.
- `create` ed `edit` leggono `next` da `request.args` o `request.form` e fanno redirect a `safe_next(next, url_for("participants.index"))`.

- [ ] **Step 1: Write the failing tests**

```python
def test_participant_edit_returns_to_next(app, client):
    # POST /participants/<id>/edit?next=/courses/<cid> -> Location termina con /courses/<cid>

@pytest.mark.parametrize("bad", ["https://evil.example/", "//evil.example", "/\\evil.example"])
def test_participant_edit_ignores_external_next(app, client, bad):
    # Location termina con /participants
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_course_ux.py -k next -v`
Expected: FAIL

- [ ] **Step 3: Implement** `safe_next`, uso nelle due route, campo hidden nel template.

- [ ] **Step 4: Run tests** — `python -m pytest -q`, tutto PASS.

- [ ] **Step 5: Commit**

```bash
git add mcorsi tests
git commit -m "Torna alla pagina di provenienza dopo la modifica del partecipante"
```

---

## Decisioni prese

- 13/11/2026: ogni operatore può iscrivere partecipanti e decidere le richieste su qualsiasi corso (Task 4).
