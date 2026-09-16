# Perslijst

Zoek publiek vermelde contactadressen op mediasites en download de resultaten via GitHub.

## Starten

1. Open **Actions**, kies **Perslijst maken** en klik **Run workflow**.
2. Kies desgewenst het maximum aantal pagina's per medium. De standaard is 12.
3. Open de afgeronde run en download onder **Artifacts** de ZIP **perslijst-csv**.

De ZIP bevat:

| Bestand | Inhoud |
| --- | --- |
| `perslijst.csv` | Gevonden adressen, automatische contactsoort en score, domeincontrole, bronpagina's en vinddatum |
| `perslijst_rapport.csv` | Per medium het aantal gelezen pagina's en adressen, fouten, blokkades en bereikte limieten |
| `perslijst_samenvatting.txt` | Totaalaantallen, Limburgse opbrengst, contactsoorten en crawlstatussen |

De workflow start ook automatisch wanneer de catalogus of scraper op `main` verandert.

## Mediabronnen toevoegen

De meegeleverde [`media_catalog.csv`](media_catalog.csv) bevat 188 afzonderlijke media. Daarin staan onder meer 51 actuele NNP-leden, 28 lokale BDU-titels, 41 lokale Rodi-edities, de dertien regionale publieke omroepen en een Limburg-selectie met hoge prioriteit. Iedere regel bewaart ook de openbare catalogusbron waarmee het medium is geselecteerd.

Voeg een medium toe met een unieke `id`, titel, start-URL, toegestaan domein, categorie, regio, prioriteit en catalogusbron. Meerdere startpagina's mogen hetzelfde `id` hebben. Media op één gedeeld platform, zoals de regionale Rodi-edities, krijgen ieder een eigen `id` en blijven daardoor afzonderlijk in de uitvoer staan.

`domains.txt` blijft beschikbaar voor een eenvoudige losse run zonder metadata:

```bash
python scrape_press.py domains.txt perslijst.csv
```

## Wat de scraper doet

- Gebruikt Scrapy met maximaal vier gelijktijdige verzoeken in totaal, één download tegelijk per medium en minimaal één seconde tussen downloads. Bij tragere websites wordt de wachttijd verhoogd.
- Leest `robots.txt`, inclusief regels voor het botprofiel. Een onbereikbare robots-pagina wordt in het rapport vermeld. Een robots-bestand met HTTP 404/410 geldt als afwezig. Een opgegeven crawl-delay wordt gevolgd tot 30 seconden; bij een langere wachttijd wordt de site overgeslagen.
- Geeft contact-, redactie-, colofon- en teampagina's prioriteit. De maximale linkdiepte is twee. Als de homepage geen contactlinks bevat, probeert hij `/contact`, `/redactie` en `/colofon`.
- Verwijdert trackingparameters en URL-fragmenten om dubbele verzoeken te beperken. Inhoudelijke queryparameters blijven behouden. Redirects naar een ander medium worden gestopt en gerapporteerd.
- Leest adressen uit zichtbare tekst, ontvangers van `mailto:`-links en expliciete `email`-velden in JSON-LD. Ook expliciet geschreven vormen zoals `redactie [at] krant [dot] nl` worden herkend. Technische scripts, HTML-comments en mailonderwerpen worden niet als contactbron gebruikt.
- Slaat herkenbare klantenservice-, advertentie-, HR- en privacyadressen over. Contactsoort en score zijn gebaseerd op het deel vóór het apenstaartje en de directe context van het adres.
- Voegt dubbele adressen binnen hetzelfde medium samen, bewaart alle gevonden bronpagina's en kiest de vondst met de hoogste score als hoofdbron. Hetzelfde adres kan bij verschillende media voorkomen.
- Markeert een e-mailadres op een ander domein als `ander_domein_controleren`. Dit kan een geldige uitgever of leverancier zijn, maar ook een tikfout op de bronpagina; de scraper corrigeert zo'n adres niet zelf.
- Herhaalt tijdelijke netwerk- en serverfouten maximaal twee keer. HTTP 429 wordt gerapporteerd zonder automatische herhaalpoging; verdere planning voor dat medium stopt.

## Resultaten beoordelen

**Contactsoort en score zijn automatische inschattingen.** `mogelijk_redactiecontact` betekent dat de pagina of tekst bij het adres op redactioneel werk wijst. `mogelijk_contact` betekent dat het adres expliciet op een contact-, colofon- of perspagina staat. De titel, categorie en regio komen uit de mediacatalogus.

De vinddatum in UTC geeft aan wanneer de run plaatsvond. Een adres wordt niet op afleverbaarheid getest. `geen_adressen_gevonden` betekent alleen dat deze crawl niets vond; het bewijst niet dat de website geen contactadres heeft. De toevoeging `_onvolledig` wijst op fouten of bereikte limieten. `niet_uitgelezen` betekent dat geen bruikbare HTML-pagina is gelezen. Bekijk dan `meldingen` en `controle_urls` in het rapport.

Een interne codefout laat de workflow mislukken. Een geblokkeerde of onbereikbare website staat in het rapport en onderbreekt de overige media niet. Bij een onderbroken crawl wordt de afsluitreden vermeld.

De scraper voert geen JavaScript uit. Contacten die pas na browserinteractie verschijnen, kunnen ontbreken. Sommige bekende challengepagina's krijgen het label `mogelijke_botblokkade`; dit is geen volledige detectie van alle blokkades. Playwright is een mogelijke volgende stap voor afzonderlijke sites als uit het rapport blijkt dat browserweergave nodig is.

De CSV gebruikt UTF-8 met BOM voor Excel. Waarden die als spreadsheetformule kunnen worden geïnterpreteerd krijgen een apostrof als voorvoegsel.

## Beschikbaarheid van downloads

De CSV's worden niet als codebestand gecommit. De run-artifacts blijven zeven dagen beschikbaar. **Artifacts van een openbare repository zijn niet privé:** ingelogde GitHub-gebruikers met leestoegang kunnen ze downloaden. Zie [GitHubs uitleg over artifact-toegang](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts).

## Ontwikkelen en testen

Python 3.12 wordt in GitHub Actions gebruikt.

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scrape_press.py media_catalog.csv perslijst.csv
```

Optioneel stelt de omgevingsvariabele `PRESS_MAX_PAGES` het maximum in van 1 tot 100 pagina's per medium. De netwerkinstellingen staan in `scrape_press.py`. De Scrapy-versie is vastgezet omdat de robots-uitbreiding ook zijn interne foutafhandeling gebruikt; voer de integratietests uit bij een upgrade.

De automatische testworkflow gebruikt een tijdelijke lokale website met bekende testadressen, serverfouten, robotsregels en redirects. Er worden daarbij geen echte media gecrawld. De perslijst-workflow draait alleen bij handmatig starten.

## Toegepaste kennis

De technische keuzes en bronnen staan in [de toelichting op de verbeteringen](docs/aanpak.md). Ze zijn gebaseerd op de relevante onderdelen van [Web scraping from 0 to hero](https://github.com/TheWebScrapingClub/webscraping-from-0-to-hero) en de actuele Scrapy-documentatie.
