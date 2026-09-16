# Toepassing van Web scraping from 0 to hero

Geraadpleegd op 15 september 2026: [TheWebScrapingClub/webscraping-from-0-to-hero](https://github.com/TheWebScrapingClub/webscraping-from-0-to-hero), commit `fcb31693a4fc9f81be561fbbbc44afdf4aa454d1`.

De repository is een kennisgids met verwijzingen. Verscheidene onderwerpen in de inhoudsopgave hebben nog geen uitgewerkt hoofdstuk. Onderstaande implementatie is voor dit project geschreven; het is geen overgenomen kant-en-klare e-mailscraper.

| Onderdeel uit de gids | Toepassing in perslijst |
| --- | --- |
| Eerst kijken waar de gewenste gegevens staan; JSON gebruiken indien beschikbaar | Expliciete `email`-velden in JSON-LD uitlezen, naast mailto en zichtbare tekst. Bekende contact-URL's staan direct in de mediacatalogus. De openbare JSON achter de NLPO-kaart is gebruikt om de actuele Limburgse omroepen te controleren. |
| Scrapy voor websites zonder benodigde browserweergave | De losse Requests-lus is vervangen door Scrapy met begrensde downloads, timeouts, retries en rapportage. |
| Weinig gelijktijdige verzoeken, vertraging en robotsregels | Eén download per medium tegelijk, wachttijd van minimaal één seconde, AutoThrottle en controle van robotsregels. |
| Het aantal verzoeken beperken | Contactlinks krijgen prioriteit, tracking-URL's worden samengevoegd en pagina- en dieptelimieten blijven actief. |
| Data formatteren | CSV met vaste kolommen, genormaliseerde adressen en alle bronnen per adres en medium. |
| Website-technologie en blokkades onderzoeken | HTTP-fouten en enkele herkenbare challengepagina's worden in het rapport vermeld. Deze herkenning is een projectkeuze en geen volledige Wappalyzer-implementatie. |
| Een browser inzetten wanneer rendering nodig is | Voorlopig HTML/JSON-LD. Het rapport biedt aanknopingspunten om later per site te bepalen of een Playwright-stap nodig is. |

## Grenzen aan de overname

De aanbevelingen voor browserfingerprints, proxyrotatie en het passeren van botbescherming zijn niet nodig voor de hier gebouwde basis. Er worden geen betaalde diensten ingeschakeld. Een browser kan bovendien alleen worden beoordeeld aan de hand van een concrete site en een test; de gids is geen bewijs dat een beschreven techniek nu bij een bepaald medium werkt.

De gids bespreekt ook juridische onderwerpen. Deze technische implementatie doet geen juridische uitspraken op basis van die samenvattingen en verstuurt geen berichten.

## Bronnen

- [Scrapy-hoofdstuk van de gids](https://github.com/TheWebScrapingClub/webscraping-from-0-to-hero/blob/fcb31693a4fc9f81be561fbbbc44afdf4aa454d1/Pages/3.Free%20Tools/Scrapy.md)
- [Playwright-hoofdstuk](https://github.com/TheWebScrapingClub/webscraping-from-0-to-hero/blob/fcb31693a4fc9f81be561fbbbc44afdf4aa454d1/Pages/3.Free%20Tools/Playwright.md)
- [Wappalyzer-hoofdstuk](https://github.com/TheWebScrapingClub/webscraping-from-0-to-hero/blob/fcb31693a4fc9f81be561fbbbc44afdf4aa454d1/Pages/3.Free%20Tools/Wappalyzer.md)
- [Scrapy: downloader middleware en robotsregels](https://docs.scrapy.org/en/2.19/topics/downloader-middleware.html)
- [Scrapy: AutoThrottle](https://docs.scrapy.org/en/2.19/topics/autothrottle.html)
- [NLPO: De Lokale Omroep in Kaart](https://www.nlpo.nl/delokaleomroepinkaart/)
- [NNP: leden van de branchevereniging voor lokale nieuwsmedia](https://www.nnp.nl/leden)
- [BDU: actuele nieuwsmerken](https://bdumedia.nl/nieuwsmerk/)
- [Rodi Media: huis-aan-huisbladen](https://www.rodimedia.nl/merken/huis-aan-huis-bladen/)
- [RPO: regionale publieke omroepen](https://www.stichtingrpo.nl/omroepen/)
- [NDP Nieuwsmedia: nieuwsbedrijven en merken](https://www.ndpnieuwsmedia.nl/nieuwsbedrijven/)

De classificatie van adressen, het bronbeheer, de specifieke foutstatussen en de tests zijn eigen projectkeuzes. Die onderdelen worden niet als letterlijke aanbevelingen uit de gids gepresenteerd.
