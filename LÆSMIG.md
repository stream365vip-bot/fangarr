# Fangarr

Fanger nye serier og film fra autobrr og lægger dem i Sonarr/Radarr ud fra dine egne regler.

- autobrr kalder `http://fangarr:8080/webhook/autobrr` (eksternt filter). Fangarr svarer 202 = stop.
- Fangarr slår titlen op (genrer, originalsprog, kanal, år, rating) og tjekker reglerne oppefra.
- Mangler TheTVDB/TMDb titlen endnu, kan den komme på **ventelisten** og prøves igen automatisk.

Faner: Regler · Test en titel (+ prøv en regel på autobrr-historikken) · Venteliste · Premierer (kommende serier fra TMDb via Seerr – tilføj eller følg) · Statistik (størrelse og afspilninger fra Tracearr pr. regel) · Oversættelser (Oversætterens tilstand, forbrug og prognose, skjult for kunderne, på vej, problemer, færdige oversættelser, statistik og indstillinger) · Log · autobrr (opret/opdatér filtre) · Indstillinger (Seerr-tjek, eksport/import, natlig eksport).

Sikringer: prøvetilstand, loft pr. døgn, pladsgrænse, kun præcise titelmatch, Seerr-tjek, Telegram ved fejl og "i orden igen", dagligt resumé.

## Oversættelser (1.9.0)
- Fangarr henter alt fra Oversætterens interne adresse (`OVERSAETTER_URL=http://oversaetter:8090`, headeren `X-Api-Token` = `OVERSAETTER_TOKEN`). Fangarr læser aldrig Oversætterens database og ændrer intet hos Oversætteren.
- Kræver Oversætteren med trin C2 (`API_PORT=8090` og `API_TOKEN` i `/opt/oversaetter/.env`).
- Telegram: oversat i går, pris, problemer og prognose i det daglige resumé. Besked, når prognosen for måneden går over loftet, og når Oversætteren ikke svarer 3 gange i træk (ca. 30 min) – og "i orden igen".
- Statistikken (pris pr. dag, hvad der kom hjem, "spildte" oversættelser, dyreste serier) læser historikken i Sonarr/Radarr og gemmes i 10 minutter.

## Skjult indtil dansk (1.10.0)
- Kræver Oversætteren med trin C3 (`REVEAL=true`). Fanen Oversættelser viser **Skjult for kunderne** (nye film/afsnit, der venter på dansk tale/tekst, med oversættelsens status og hvornår sikkerhedsnettet viser dem), **Vist i Plex** (7 dage; ✓ klar eller ⏰ uden dansk) og **På vej** (udgivelser, Sonarr/Radarr holder tilbage pga. ventetiden – `status=delay` i køen).
- Telegram: én besked, hver gang noget er vist **uden** dansk tekst (sikkerhedsnet). Fangarr husker, hvad der er meldt (tabellen `reveal_notified`), så samme titel kun meldes én gang.
- Nødløsning: svarer Oversætteren ikke i `REVEAL_FALLBACK_MINUTES` (60), beder Fangarr selv Plex scanne mapperne for alle importer fra de sidste 48 timer – og derefter hver time de nye. Besked, når den går i gang, og "svarer igen", når Oversætteren er tilbage. Kræver `PLEX_URL` og `PLEX_TOKEN` i `fangarr.env` (valgfri `PLEX_PATH_MAP="fra=til"`, hvis Plex ser mapperne et andet sted). Nødløsningen kører kun, hvis Fangarr har set trinnet slået til.

## Knapper og Seerr uden ventetid kun første gang (1.11.0)
- Kræver Oversætteren med trin C4. Fanen Oversættelser › **Oversæt en titel**: søg en serie/film i Sonarr/Radarr, se afsnit pr. sæson (har dansk / i gang / mangler) og prisen, vælg sæsoner og tryk **Oversæt nu** (advarsel, hvis prisen er mere end der er tilbage af månedens loft – Oversætteren stopper selv ved loftet). **Ingen ventetid fremover** sætter mærket `straks` (fjernes aldrig automatisk); knappen kan også fjerne det igen.
- **Problemer:** titler med dansk tale (`ikke_muligt`) er skjult som standard (flueben viser dem). **Prøv igen** behandler titlen forfra i næste runde, **Opgiv** giver status `opgivet`, så den ikke vælges igen. Færdige titler kan ikke røres.
- **Seerr-ønsker** (hvert 2. minut): ønsker på en serie, der allerede findes i sonarr2, får mærket `seerr-straks`, og Fangarr søger efter de ønskede sæsoner, så første download kommer uden ventetid. Serier med `seerr-straks` mister mærket, når første afsnit efter mærket er kommet hjem. Kræver at `seerr-straks` står i delay-profilen uden ventetid i sonarr2, og at Seerr giver nye serier mærket `seerr-straks`.
- Alt logges i Fangarrs log (`oversæt nu`, `ingen ventetid`, `seerr uden ventetid`, `seerr-straks fjernet`).

## Filer
- `app/main.py` – server (FastAPI) · `app/static/index.html` – interface · `app/VERSION`
- `fangarr.env.eksempel` – skabelon til `fangarr.env` (API-nøgler). `chmod 600`. **Kommer aldrig i git.**
- Data: `/opt/fangarr/data/fangarr.db`. Natlige eksportfiler: `/opt/fangarr/data/backup/`.
- `docker-compose.yml` laves af Saltbox og ligger kun på serveren.

## Opdatering
```
cd /opt/fangarr && ./opdater.sh
```
Log: `docker logs --tail 50 fangarr`
