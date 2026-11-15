# nyt-login – Stream365-guiden bag Plex-login

En lille app, der viser en statisk side (nyhedsbrevet på `nyt.stream365.vip`), men kun for Plex-konti med adgang til Stream365-serveren. Den hører ikke til Fangarr – koden ligger bare i samme repo, så den kan hentes med `git pull`.

## Sådan virker den
1. Brugeren trykker **Log ind med Plex** og godkender hos Plex (samme metode som Seerr).
2. Appen spørger plex.tv, hvilke servere kontoen har adgang til.
3. Er Stream365-serveren på listen, huskes brugeren på enheden i 90 dage (cookie) og ser siden. Ellers: "Kun for brugere af Stream365".

- **Login-koden laves i brugerens egen browser** (fra 13. nov. 2026, som Seerr). Så viser Plex' login brugerens egen adresse og by – ikke feeders (65.21.142.239, Helsinki, Finland) med en "Sikkerhedsadvarsel". Kan browseren ikke få en kode hos plex.tv, falder knappen automatisk tilbage til den gamle metode, hvor feeder beder om koden (så vises Finland igen, men login virker).
- Appen ser aldrig brugerens kodeord. Brugerens Plex-nøgle bruges til ét opslag og gemmes ikke.
- Appen har ingen af dine nøgler. Serverens id hentes fra `PLEX_URL/identity`, som ikke kræver nøgle.
- Adgangen tjekkes, **når brugeren logger ind**. En bruger, du fjerner i Plex, kan derfor stadig læse siden på en enhed, hvor de allerede er logget ind, til de 90 dage er gået. Log alle ud med det samme: `rm /opt/nyt/data/secret && cd /opt/nyt && docker compose restart` (alle skal så logge ind igen).
- Loggen (`docker logs nyt`) viser "Adgang givet til Plex-kontoen …" og "Afvist: …".

## Filer på feeder
- `/opt/nyt/docker-compose.yml` – lavet med `sb install generate-traefik-template` (uden Authelia, uden API-router), `build: /opt/fangarr/nyt-login`.
- `/opt/nyt/site/` – selve siden (`index.html`, `img/` …). Monteres skrivebeskyttet som `/site`.
- `/opt/nyt/data/` – `secret` (underskriver cookies) og `client_id` (appens id hos Plex). Monteres som `/config`.

## Indstillinger (miljøvariabler, alle valgfri)
`PUBLIC_URL` (standard `https://nyt.stream365.vip`), `PLEX_URL` (`https://plex.stream365.vip`), `PLEX_MACHINE_ID` (hvis serverens id ikke skal hentes automatisk), `SESSION_DAYS` (90), `CONTACT_TEXT`, `UPTIME_URL`, `UPTIME_SLUG` (kunder), `STATUS_LINKS` (se Driftstatus), `STAT` (1; 0 slår tælleren fra), `STAT_EXCLUDE` (Stream365), `STAT_DAYS` (90), `STAT_DIR` (se Tæller).

## Opdatering
- Ny udgave af siden: læg filerne i `/opt/nyt/site/` – ingen genstart.
- Ny udgave af appen: `cd /opt/fangarr && git pull` og derefter `cd /opt/nyt && docker compose up -d --build`.
- Kontrol: `docker exec nyt python -c "import urllib.request as u;print(u.urlopen('http://127.0.0.1:8080/health').read().decode())"` → `"ok":true,"site":true,"server_id":true`.

## Regler ved første login (fra 12. nov. 2026)
- Ligger filen `/opt/nyt/site/_regler.json` der, møder en bruger reglerne og tre spørgsmål, **første gang** de logger ind. Guiden (og billederne) vises først, når alle tre svar er rigtige. Forkerte svar markeres med rødt, uden at det rigtige svar afsløres.
- Hvem der har accepteret, og hvornår, står i `/opt/nyt/data/accepteret.json` (Plex-id, brugernavn, tidspunkt, reglernes version). Vis den: `cat /opt/nyt/data/accepteret.json`.
- Accepten følger Plex-kontoen, ikke enheden – brugeren spørges ikke igen på en ny enhed.
- **Nye regler, som alle skal acceptere igen:** ret teksten i `_regler.json`, og sæt `"version"` ét tal op. Rettelser uden nyt versionsnummer vises kun for nye brugere.
- Filer, hvis navn begynder med `_` eller `.`, vises aldrig for brugerne.
- Fjern filen (eller omdøb den), hvis reglerne ikke skal vises.

## Adresse
`PUBLIC_URL` er guidens adresse (`https://guide.stream365.vip`). Adresser i `OLD_HOSTS` (fx `nyt.stream365.vip`) sendes videre dertil. Begge adresser skal stå i Traefik-reglen i `docker-compose.yml` og have en DNS-post til feeder (grå sky).

## Driftstatus øverst i guiden (fra 13. nov. 2026)
- Er `UPTIME_URL` sat (fx `http://uptime:3001`), får alle HTML-sider en statuslinje øverst: én lampe pr. monitor på Uptime Kuma-statussiden `UPTIME_SLUG` (Plex, Seerr, IPTV 1–3), status (Kører/Nede/Ustabil/Vedligehold) og oppetid de seneste 24 timer. Linjen opdateres hvert minut.
- Kun for brugere, der er logget ind og har accepteret reglerne (`/api/status` giver ellers 401). Appen spørger Uptime Kuma internt i Docker-netværket – Uptime Kuma åbnes ikke udefra.
- `STATUS_LINKS`: tekst vist under en monitor med knappen Kopiér, adskilt med `;` – `Monitornavn=tekst`. Navnet skal være monitorens navn på statussiden (store/små bogstaver ligegyldige).
- En hændelse (Incident) på statussiden i Uptime Kuma vises som besked i linjen; aktive vedligeholdelsesvinduer vises som "Planlagt vedligehold".
- **Fra 15. nov. 2026 er linjen aldrig foldet helt sammen:** der står altid "Driftstatus", en samlet tekst og en lampe med navn for hver tjeneste (Plex, Seerr, IPTV 1–3) – også på telefon. Knappen **Adresser og oppetid** (på telefon: **Adresser**) viser IPTV-adresserne og oppetiden. På computer er den foldet ud fra start. Ved problemer, en hændelse eller planlagt vedligehold skifter hele linjen farve (rød = nede, gul = ustabil, blå = vedligehold/besked) og folder sig ud af sig selv.
- Navnet i `STATUS_LINKS` sammenlignes uden mellemrum og tegn, så `IPTV 3`, `IPTV3` og `iptv-3` er samme monitor. Passer et navn ikke til nogen monitor, står det i loggen: `docker logs nyt 2>&1 | grep STATUS_LINKS`. Står der ingen adresse i `STATUS_LINKS`, bruges monitorens egen adresse, hvis "vis adresse" er slået til for den på statussiden i Uptime Kuma.
- Svarer Uptime Kuma ikke: "Driftstatus kan ikke hentes lige nu" (grå). Svaret gemmes i 30 sek., så Uptime Kuma spørges højst to gange i minuttet.
- Kontrol (feeder): `docker exec nyt python -c "import urllib.request as u;print(u.urlopen('http://127.0.0.1:8080/health').read().decode())"` → `"status":true`.

## Tæller – hvem har været inde, og hvad har de set på (fra 15. nov. 2026)
Vises i **Fangarr › Guide** med rigtige navne fra Kunder (Tautulli). Kunderne ser ingenting til tælleren.
- **Hvad der gemmes:** login (Plex-login på en enhed), besøg (guiden åbnes efter mindst 30 minutters pause), læste afsnit (afsnittet har stået midt på skærmen i 5 sekunder) og søgeord (mindst 3 tegn, efter 1,5 sekunds pause). For hver: tidspunkt, Plex-id og brugernavn. **Ingen IP-adresser.**
- **Hvor:** én fil pr. dag i `/opt/nyt/data/statistik/` (fx `2026-11-15.jsonl`) plus `accepteret.json` (kopi af listen over accepterede regler). Filer ældre end `STAT_DAYS` (90) dage slettes automatisk.
- **Hvem tælles ikke:** konti i `STAT_EXCLUDE` (standard `Stream365`) – de får slet ikke tælle-scriptet, og intet om dem gemmes.
- Den gamle adresse `nyt.stream365.vip` sender videre til guiden, før noget tælles – ingen tælles dobbelt.
- Afsnit findes automatisk i siden: `<section id="…">` (overskriften i afsnittet bruges som navn), ellers overskrifter med id (`<h2 id="…">`). Søgefeltet er `<input type="search">` eller et felt med "søg" i navn/hjælpetekst. Siden selv skal ikke ændres.
- **Fangarr skal kunne læse mappen:** tilføj under `volumes:` i `/opt/fangarr/docker-compose.yml`: `- "/opt/nyt/data/statistik:/guide-stat:ro"` og kør `cd /opt/fangarr && docker compose up -d`.
- Se dagens hændelser (feeder): `tail -n 20 /opt/nyt/data/statistik/$(date +%F).jsonl`
- Slå tælleren fra: `STAT: "0"` i compose-filen og `cd /opt/nyt && docker compose up -d`. Slet alt, der er talt: `rm -r /opt/nyt/data/statistik`.
