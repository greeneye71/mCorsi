# Formato JSON per l'importazione dei questionari

Questo documento descrive il formato dei file JSON che mCorsi accetta in
**Questionari → Importa** (`POST /questionnaires/import`, riservato allo staff).
È lo stesso formato prodotto dall'esportazione JSON di un questionario, quindi
un file esportato può essere reimportato così com'è, anche in un altro corso o
in un'altra installazione.

Riferimento nel codice: `mcorsi/services/questionnaire_transfer.py`.

## Requisiti del file

| Requisito | Valore |
|---|---|
| Estensione | `.json` |
| Dimensione massima | 1 MB |
| Codifica | UTF-8 (il BOM iniziale è ammesso) |
| Contenuto | un singolo oggetto JSON (non un array) |

Il corso di destinazione non è scritto nel file: si sceglie nel modulo di
importazione.

## Struttura generale

```json
{
  "format": "mcorsi.questionnaire",
  "schema_version": 1,
  "exported_at": "2026-11-11T09:00:00+00:00",
  "questionnaire": {
    "title": "...",
    "instructions": "...",
    "passing_percentage": 70,
    "max_attempts": 3,
    "version": 1,
    "questions": [ ... ]
  }
}
```

### Campi di primo livello

| Campo | Tipo | Obbligatorio | Note |
|---|---|---|---|
| `format` | stringa | sì | deve valere esattamente `"mcorsi.questionnaire"` |
| `schema_version` | intero | sì | deve valere `1` |
| `exported_at` | stringa | no | informativo, ignorato in importazione |
| `questionnaire` | oggetto | sì | definizione del questionario (vedi sotto) |

### Oggetto `questionnaire`

| Campo | Tipo | Obbligatorio | Default | Vincoli |
|---|---|---|---|---|
| `title` | stringa | sì | — | non vuoto, max 240 caratteri |
| `instructions` | stringa | no | `""` | max 5000 caratteri |
| `passing_percentage` | intero | sì | — | da 1 a 100 |
| `max_attempts` | intero | no | `3` | da 1 a 20 |
| `version` | intero | no | `1` | da 1 a 1.000.000 |
| `questions` | array di oggetti | sì | — | da 1 a 500 domande |

### Oggetto domanda (elemento di `questions`)

| Campo | Tipo | Obbligatorio | Vincoli |
|---|---|---|---|
| `prompt` | stringa | sì | testo della domanda, non vuoto, max 5000 caratteri |
| `response_type` | stringa | sì | `"single"` (scelta singola) oppure `"multiple"` (scelta multipla) |
| `options` | array di oggetti | sì | da 2 a 6 opzioni |

L'ordine delle domande nel file è l'ordine in cui verranno mostrate.

### Oggetto opzione (elemento di `options`)

| Campo | Tipo | Obbligatorio | Default | Vincoli |
|---|---|---|---|---|
| `text` | stringa | sì | — | non vuoto, max 2000 caratteri |
| `is_correct` | booleano | sì | — | deve essere `true` o `false` JSON (non `"true"`, non `1`) |
| `score` | numero o stringa | no | `0` | da 0 a 10000, massimo 2 decimali (es. `1`, `2.5`, `"0.75"`) |

L'ordine delle opzioni nel file è l'ordine in cui verranno mostrate.

## Regole di validazione

Oltre ai vincoli dei singoli campi, il questionario viene rifiutato se:

- una domanda non ha almeno una opzione con `is_correct: true`;
- una domanda `"single"` ha più di una opzione corretta (deve averne
  **esattamente una**);
- un'opzione corretta ha `score` uguale a 0 (le risposte corrette devono avere
  punteggio **positivo**);
- il punteggio massimo complessivo è 0.

Le opzioni errate hanno sempre punteggio 0: se nel file un'opzione con
`is_correct: false` ha uno `score` diverso da zero, il valore viene comunque
controllato (0–10000, 2 decimali) ma poi azzerato in importazione, senza errore.

Altre note sul trattamento dei valori:

- i testi vengono ripuliti dagli spazi iniziali e finali; un testo composto solo
  da spazi conta come vuoto;
- per i campi interi è preferibile usare numeri interi JSON (`70`); stringhe
  numeriche come `"70"` sono accettate, i booleani no;
- per `score` è preferibile usare una stringa (`"2.50"`) o un numero con al
  massimo due decimali; l'esportazione scrive sempre una stringa;
- i campi non previsti vengono ignorati (non causano errore).

## Punteggio e superamento

- **Punteggio massimo** = somma degli `score` di tutte le opzioni corrette di
  tutte le domande.
- **Domanda a scelta singola**: il partecipante sceglie una sola opzione e
  ottiene lo `score` dell'opzione se è corretta, 0 altrimenti.
- **Domanda a scelta multipla**: se tra le opzioni scelte ce n'è anche una sola
  errata, la domanda vale 0; altrimenti si ottiene la somma degli `score` delle
  opzioni corrette selezionate (punteggio parziale se non le ha scelte tutte).
- Il tentativo è **superato** quando
  `punteggio × 100 / punteggio massimo ≥ passing_percentage`.
- Ogni partecipante ha a disposizione `max_attempts` tentativi.

Esempio: tre domande da 1 punto ciascuna e `passing_percentage: 70` → servono
almeno 2,1 punti, quindi tutte e tre le risposte giuste. Con
`passing_percentage: 66` bastano 2 risposte giuste su 3.

## Cosa succede in importazione

- Il questionario viene creato nel corso scelto **come bozza** (non pubblicato)
  e posizionato in fondo all'elenco dei questionari del corso.
- La `version` salvata è quella del file **+ 1** (un file con `"version": 1`
  produce un questionario in versione 2).
- Non vengono importati tentativi, risposte o altri dati dei partecipanti: il
  formato contiene solo la definizione del questionario.
- L'operazione viene registrata nel registro di audit come
  `questionnaire.imported`.
- Dopo l'importazione compare il messaggio *"Questionario importato come bozza.
  Controllalo prima di pubblicarlo."*: verificare il contenuto e pubblicarlo
  dalla pagina del questionario.

## Esempio completo

```json
{
  "format": "mcorsi.questionnaire",
  "schema_version": 1,
  "questionnaire": {
    "title": "Verifica finale - Sicurezza sul lavoro (rischio basso)",
    "instructions": "Rispondi a tutte le domande. Per superare il test serve almeno il 70% del punteggio.",
    "passing_percentage": 70,
    "max_attempts": 3,
    "version": 1,
    "questions": [
      {
        "prompt": "Chi è il soggetto che ha la responsabilità principale della sicurezza in azienda?",
        "response_type": "single",
        "options": [
          { "text": "Il datore di lavoro", "is_correct": true, "score": "1" },
          { "text": "Il rappresentante dei lavoratori per la sicurezza", "is_correct": false },
          { "text": "Il medico competente", "is_correct": false }
        ]
      },
      {
        "prompt": "Quali tra questi sono dispositivi di protezione individuale (DPI)?",
        "response_type": "multiple",
        "options": [
          { "text": "Guanti di protezione", "is_correct": true, "score": "0.5" },
          { "text": "Occhiali di sicurezza", "is_correct": true, "score": "0.5" },
          { "text": "Estintore", "is_correct": false },
          { "text": "Cartellonistica di sicurezza", "is_correct": false }
        ]
      },
      {
        "prompt": "In caso di incendio si deve usare l'ascensore per evacuare l'edificio.",
        "response_type": "single",
        "options": [
          { "text": "Vero", "is_correct": false, "score": 0 },
          { "text": "Falso", "is_correct": true, "score": 1 }
        ]
      }
    ]
  }
}
```

Punteggio massimo dell'esempio: 1 + (0,5 + 0,5) + 1 = 3. Soglia: 70% di 3 = 2,1.

## Messaggi di errore frequenti

Prima della lettura del contenuto possono comparire:

- `Seleziona un corso e un file JSON valido.`: corso non scelto o file senza
  estensione `.json`;
- `Il file JSON supera il limite di 1 MB.`: file troppo grande.

Gli altri problemi sono segnalati con *"Importazione non riuscita: …"* seguito
da uno di questi messaggi.

| Messaggio | Causa |
|---|---|
| messaggio tecnico del parser (es. `Expecting ',' delimiter: line 5 column 3`) | sintassi JSON non valida (virgole finali, apici singoli, commenti…) o file non UTF-8 |
| `Il contenuto JSON deve essere un oggetto.` | la radice è un array o un valore semplice |
| `Formato non riconosciuto: atteso mcorsi.questionnaire.` | `format` mancante o diverso |
| `Versione del formato non supportata: è richiesta la versione 1.` | `schema_version` mancante o diverso da `1` |
| `La definizione del questionario non è presente.` | manca l'oggetto `questionnaire` |
| `Il campo 'title' è obbligatorio.` | titolo mancante o vuoto |
| `Il campo 'X' deve essere testuale.` | un testo è un numero, `null`, ecc. |
| `Il campo 'X' supera N caratteri.` | testo troppo lungo |
| `Il campo 'X' deve essere un numero intero.` / `deve essere compreso tra A e B.` | intero non valido o fuori intervallo |
| `Il questionario deve contenere almeno una domanda.` | `questions` mancante, vuoto o non array |
| `Sono consentite al massimo 500 domande.` | troppe domande |
| `La domanda N non è valida.` | la domanda non è un oggetto |
| `Il tipo della domanda N deve essere 'single' o 'multiple'.` | `response_type` errato |
| `La domanda N deve avere da 2 a 6 opzioni.` | numero di opzioni fuori intervallo |
| `L'opzione M della domanda N non è valida.` | opzione non oggetto, o `is_correct` mancante / non booleano |
| `Il campo '...score' non è un punteggio valido.` / `deve essere compreso tra 0 e 10000.` / `può avere al massimo due decimali.` | `score` non valido |
| `La domanda N non ha risposte corrette.` | nessuna opzione con `is_correct: true` |
| `La domanda N a scelta singola deve avere una sola risposta corretta.` | più opzioni corrette in una `"single"` |
| `Le risposte corrette della domanda N devono avere punteggio positivo.` | opzione corretta con `score` 0 o assente |

Nei messaggi i riferimenti alle domande e alle opzioni partono da 1
(es. `questions[2].options[3].text` = terza opzione della seconda domanda).
