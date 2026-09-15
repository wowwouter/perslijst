# Perslijst

Deze scraper zoekt op de opgegeven mediasites naar publiek vermelde contactadressen. De CSV bevat `medium`, `domein`, `email`, `type`, `score` en `bron_url`. De score is een automatische inschatting; controleer de adressen en bronpagina's voordat je ze gebruikt.

## Starten via GitHub

1. Pas [`domains.txt`](domains.txt) aan: één mediadomein per regel. Begin gerust met de meegeleverde Nederlandse sites.
2. Open het tabblad **Actions** en kies **Perslijst maken**.
3. Klik **Run workflow** en wacht tot de run klaar is.
4. Open de run en download onder **Artifacts** de ZIP `perslijst-csv`. Daarin staat `perslijst.csv`.

De CSV wordt niet aan de openbare repository toegevoegd. GitHub bewaart het run-artifact zeven dagen. De workflow draait alleen wanneer je hem zelf start.

## Lokaal (optioneel)

```bash
python -m pip install -r requirements.txt
python scrape_press.py domains.txt perslijst.csv
```

De crawler blijft op het domein van ieder medium, volgt links naar contact- en redactiepagina's en houdt rekening met `robots.txt`. Sommige media publiceren geen e-mailadres, blokkeren bots of tonen adressen alleen via JavaScript. Zulke adressen verschijnen niet in de output. Gebruik de bron-URL om relevantie en actualiteit te beoordelen; verstuur geen ongerichte bulkmail.
