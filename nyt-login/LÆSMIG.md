# nyt-login – Stream365-guiden bag Plex-login

En lille app, der viser en statisk side (nyhedsbrevet på `nyt.stream365.vip`), men kun for Plex-konti med adgang til Stream365-serveren. Den hører ikke til Fangarr – koden ligger bare i samme repo, så den kan hentes med `git pull`.

## Sådan virker den
1. Brugeren trykker **Log ind med Plex** og godkender hos Plex (samme metode som Seerr).
2. Appen spørger plex.tv, hvilke servere kontoen har adgang til.
3. Er Stream365-serveren på listen, huskes brugeren på enheden i 90 dage (cookie) og ser siden. Ellers: "Kun for brugere af Stream365".

- Appen ser aldrig brugerens kodeord. Brugerens Plex-nøgle bruges til ét opslag og gemmes ikke.
- Appen har ingen af dine nøgler. Serverens id hentes fra `PLEX_URL/identity`, som ikke kræver nøgle.
- Adgangen tjekkes, **når brugeren logger ind**. En bruger, du fjerner i Plex, kan derfor stadig læse siden på en enhed, hvor de allerede er logget ind, til de 90 dage er gået. Log alle ud med det samme: `rm /opt/nyt/data/secret && cd /opt/nyt && docker compose restart` (alle skal så logge ind igen).
- Loggen (`docker logs nyt`) viser "Adgang givet til Plex-kontoen …" og "Afvist: …".

## Filer på feeder
- `/opt/nyt/docker-compose.yml` – lavet med `sb install generate-traefik-template` (uden Authelia, uden API-router), `build: /opt/fangarr/nyt-login`.
- `/opt/nyt/site/` – selve siden (`index.html`, `img/` …). Monteres skrivebeskyttet som `/site`.
- `/opt/nyt/data/` – `secret` (underskriver cookies) og `client_id` (appens id hos Plex). Monteres som `/config`.

## Indstillinger (miljøvariabler, alle valgfri)
`PUBLIC_URL` (standard `https://nyt.stream365.vip`), `PLEX_URL` (`https://plex.stream365.vip`), `PLEX_MACHINE_ID` (hvis serverens id ikke skal hentes automatisk), `SESSION_DAYS` (90), `CONTACT_TEXT`.

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
