# Fangarr

Fanger nye serier og film fra autobrr og lægger dem i Sonarr/Radarr ud fra dine egne regler.

- autobrr kalder `http://fangarr:8080/webhook/autobrr` (eksternt filter). Fangarr svarer 202 = stop.
- Fangarr slår titlen op (genrer, originalsprog, kanal, år, rating) og tjekker reglerne oppefra.
- Mangler TheTVDB/TMDb titlen endnu, kan den komme på **ventelisten** og prøves igen automatisk.

Faner: Regler · Test en titel (+ prøv en regel på autobrr-historikken) · Venteliste · Premierer (kommende serier fra TMDb via Seerr – tilføj eller følg) · Statistik (størrelse og afspilninger fra Tracearr pr. regel) · Oversættelser (Oversætterens tilstand, forbrug og prognose, problemer, færdige oversættelser, statistik og indstillinger) · Log · autobrr (opret/opdatér filtre) · Indstillinger (Seerr-tjek, eksport/import, natlig eksport).

Sikringer: prøvetilstand, loft pr. døgn, pladsgrænse, kun præcise titelmatch, Seerr-tjek, Telegram ved fejl og "i orden igen", dagligt resumé.

## Oversættelser (1.9.0)
- Fangarr henter alt fra Oversætterens interne adresse (`OVERSAETTER_URL=http://oversaetter:8090`, headeren `X-Api-Token` = `OVERSAETTER_TOKEN`). Fangarr læser aldrig Oversætterens database og ændrer intet hos Oversætteren.
- Kræver Oversætteren med trin C2 (`API_PORT=8090` og `API_TOKEN` i `/opt/oversaetter/.env`).
- Telegram: oversat i går, pris, problemer og prognose i det daglige resumé. Besked, når prognosen for måneden går over loftet, og når Oversætteren ikke svarer 3 gange i træk (ca. 30 min) – og "i orden igen".
- Statistikken (pris pr. dag, hvad der kom hjem, "spildte" oversættelser, dyreste serier) læser historikken i Sonarr/Radarr og gemmes i 10 minutter.

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
