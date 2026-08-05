# Checklist di rilascio mCorsi

## Controlli automatici

Eseguire dall'ambiente virtuale nella radice del progetto:

```powershell
python -m pip install -r requirements.txt
python -m pytest
python -m flask --app wsgi db upgrade
python -m flask --app wsgi db check
python -m flask --app wsgi version
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1
```

Il test end-to-end copre il percorso corso → OTP partecipante → anagrafica →
ammissione → questionario → presenza → attestato → portale partecipante.

## Prima messa in esercizio

- generare e conservare separatamente i quattro segreti;
- creare l'amministratore e verificare la gestione operatori dalla webapp;
- configurare SMTP e inviare una mail di prova reale;
- caricare una firma e generare un attestato di prova con LibreOffice;
- impostare una destinazione backup su disco o sistema distinto;
- installare i processi web, MCP, promemoria e backup;
- pubblicare gli hostname Cloudflare verso le porte web e MCP previste;
- limitare la regola firewall web al profilo/rete privata e non configurare
  inoltri di porta sul router;
- verificare che le porte configurate (predefinite: web 5100, MCP 8001) non
  siano già occupate;
- creare un token MCP a privilegi minimi e provarlo dal client previsto;
- verificare desktop e smartphone reali, in particolare questionario e OTP;
- registrare informativa privacy, tempi di conservazione e responsabili degli
  accessi prima di importare dati personali reali.

## Verifica periodica

- ogni giorno: stato servizi, `/health/ready`, coda email e backup creato;
- ogni mese: scadenze, utenti interni e token MCP attivi;
- ogni tre mesi: ripristino di prova su una directory/database separati;
- dopo ogni aggiornamento: backup, migrazioni, controllo versione, test e smoke
  test.
