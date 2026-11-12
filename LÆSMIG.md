# Fangarr

Fanger nye serier og film fra autobrr og lægger dem i Sonarr/Radarr ud fra dine egne regler.

- autobrr kalder `http://fangarr:8080/webhook/autobrr` (eksternt filter). Fangarr svarer 202 = stop.
- Fangarr slår titlen op (genrer, originalsprog, kanal, år, rating) og tjekker reglerne oppefra.
- Mangler TheTVDB/TMDb titlen endnu, kan den komme på **ventelisten** og prøves igen automatisk.

Faner: Regler · Test en titel (+ prøv en regel på autobrr-historikken) · Venteliste · Premierer (kommende serier fra TMDb via Seerr – tilføj eller følg) · Statistik (størrelse og afspilninger fra Tracearr pr. regel) · Kontodeling (konti, hvor to tv afspiller samtidig fra hver sin adresse – fra Tautulli) · Oversættelser (Oversætterens tilstand, forbrug og prognose, skjult for kunderne, på vej, problemer, færdige oversættelser, statistik og indstillinger) · Log · autobrr (opret/opdatér filtre) · Indstillinger (Seerr-tjek, eksport/import, natlig eksport).

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

## Kontodeling (1.12.0 – 1.13.0)
Fanen **Kontodeling** finder konti, hvor **to tv afspiller samtidig fra hver sin adresse** (kontoreglen), og viser, hvilke enheder der er kundens egne. Telefoner, tablets og computere tæller ikke som tv. Intet kører af sig selv, intet sendes til Telegram, og Fangarr blokerer ingen. Samme forklaring står i selve fanen under **Sådan læser du fanen**.

**Opsætning:** `TAUTULLI_URL` og `TAUTULLI_APIKEY` i `fangarr.env`. Fangarr læser kun fra Tautulli (`get_history`), og API-nøglen står aldrig i loggen eller i fejlbeskeder. Kopiér nøglen fra Mediabox til feeder uden at vise den (køres fra en maskine med adgang til begge servere; svaret viser kun, hvor mange tegn nøglen har):
```
ssh mediabox "grep -m1 '^api_key' /opt/tautulli/config.ini" | ssh feeder 'K=$(cut -d= -f2 | tr -d " \"\r"); if grep -q "^TAUTULLI_APIKEY=" /opt/fangarr/fangarr.env; then echo "findes allerede"; else printf "\nTAUTULLI_URL=https://tautulli.stream365.vip\nTAUTULLI_APIKEY=%s\n" "$K" >> /opt/fangarr/fangarr.env; echo "tilføjet (${#K} tegn)"; fi'
```

### Hvad bliver talt
- **Overlap:** to tv med hver sin offentlige adresse, der kører samtidig i mindst *Mindst (minutter)* (standard 10). Tid på pause trækkes fra. Overlap mellem de samme to tv med under 20 minutters pause regnes som ét. Afspilninger over 8 timer skæres af.
- **Aften:** fra kl. 05 til kl. 05. 🔴 = mindst *Rød fra (aftener)* aftener med overlap (standard 5), 🟡 = 1 eller flere, 🟢 = ingen.
- **Tv eller mobil** afgøres af platform og app (fx `Plex for Android (TV)` = tv, `Plex for Android (Mobile)` = mobil). Enheder, der ikke kan bestemmes, tælles ikke som tv og står som *Ukendt* under **Enhedstyper** nederst.
- **Chromecast** får nyt machine_id ved hver cast, så alle casts fra samme adresse regnes som én enhed (én linje pr. sted).

### Hvilke enheder er kundens? (1.13.0 – kæden)
Der gættes ikke ud fra antal afspilninger. Fangarr bruger **hele** Tautullis historik:
1. **Udgangspunktet er kontoens første tv.** Er det senere flyttet væk fra en fast adresse, mens andre blev, er det dem, der blev, som regnes som kunden.
2. **Et tv kommer med i kæden**, når det har stået på samme adresse som et tv i kæden inden for et døgn på mindst 3 forskellige dage, eller har brugt samme faste adresse (en adresse brugt på mindst 5 dage). Tv, der kun er brugt få dage, hægtes på det sted, de har delt adresse med.
3. **Gået hver til sit:** to tv, der begge er brugt (3+ dage) senere end 14 dage efter deres sidste fælles dag, står ikke længere sammen.
4. **Flytning:** en telefon/tablet/computer set på mindst 3 dage både på det gamle og det nye sted binder dem sammen – men kun hvis det gamle sted holdt op, omkring da det nye begyndte (højst 60 dages overlap). To steder, der er i brug samtidig i lang tid, er to hjem. Under 3 dage hvert sted er for lidt: det nye sted bliver **Uafklaret**, og du afgør det selv (1.13.1 – før kom svage flytninger med i kæden, og korte "mellemsteder" kunne binde to hjem sammen).
5. Mærker: **Kundens**, **Tidligere hos kunden** (stod hos kunden, men er siden brugt et andet sted), **Aldrig hos kunden**, **Uafklaret** (kundens kendte enheder er ikke brugt i 45 dage, og et andet sted er i brug – muligvis en flytning uden spor) og **Godkendt undtagelse**. Ved hver enhed står **beviset**.
6. Overlap mellem to af kundens egne steder (fx under en flytning) tæller ikke.

**⚠ ved navnet** (1.13.1): kun når kontoen blev brugt flere steder i de første 14 dage, eller et uafklaret tv er i brug (i overlap eller 5+ afspilninger). Er kontoen ældre end Tautullis historik, står det som en almindelig oplysning (ℹ). Chromecast på et net med skiftende adresser, som ikke kan kobles til et tv, samles til ét sted pr. net.

Begrænsninger: var kontoen delt fra første dag, eller er kunden ældre end Tautullis historik, kan udgangspunktet være forkert (gul bemærkning ⚠ på brugeren). Sommerhus, VPN på tv'et og flytning uden spor kræver, at du selv afgør det.

### Fanen fra 1.14.0 – bygget til at blokere
Fanen svarer på ét spørgsmål pr. bruger: **hvilke tv har aldrig stået hos kunden, og hvordan blokeres de bedst i Tracearr uden at ramme kundens egne?** Fangarr blokerer ikke selv og skriver ikke til nogen (beskedfunktionen fra 1.13 er fjernet).

- **Fem grupper** i stedet for rød/gul: 🔴 *Kan blokeres* (fremmede tv bruges samtidig med kundens) · 🟡 *Afgør selv* (Fangarr kan ikke se, hvilket sted der er kundens – vælg det, så flytter brugeren gruppe) · ⚙️ *I gang* (brugere med en sag) · ⚪ *Fremmede tv uden samtidig brug* (tilladt efter kontoreglerne) · 🟢 *Ingen fremmede tv*. De to sidste vises med "Vis alle grupper".
- **Konklusion** øverst på hver bruger i almindeligt sprog.
- **Bedste blokering:** op til fem slags Tracearr-regler prøves af på brugerens egne tv-afspilninger fra de seneste 90 dage. For hver vises, hvor mange fremmede afspilninger reglen ville have stoppet, hvor mange af kundens egne, præcis hvad der skal stå i reglen, hvorfor den virker, og hvad man skal passe på. Den anbefalede er den, der rammer flest fremmede og ingen af kundens.
  - *Stop appen* (`Client/Player`) – når de fremmede tv bruger en app, kundens egne ikke har brugt det seneste år.
  - *Stop tv på de fremmede adresser* (`Device Type` TV + `IP Range`) – når de fremmede tv har fast adresse (brugt 4+ dage).
  - *Stop tv på det fremmede net* (`IP Range` med et helt net, fx `109.56.0.0/16`) – mobilt bredbånd med skiftende adresser, som kundens tv ikke har brugt det seneste år.
  - *Stop appen uden for kundens adresse* og *Tillad kun tv på kundens adresse* – kræver, at kunden har fast adresse (98 % af afspilningerne på højst 2 adresser).
  - Tracearr kan ikke blokere ét bestemt machine_id. Feltnavnene er fra Tracearrs kildekode (nov. 2026) – tjek dem i din udgave.
- **Steder i stedet for enheder:** ét kort pr. sted (de tv, der står sammen) med mærke, bevis og knapperne *Dette er kundens*, *Ikke kundens*, *Godkend undtagelse* og *Fjern valg*. Afgørelsen gælder hele stedet og gemmes (`sharing_marks`). Enheder, adresser og id'er er foldet sammen under stedet.
- **Samme tv, nyt id:** Samsung m.fl. skifter machine_id med jævne mellemrum. Et tv med samme navn og app, der begynder, når et andet er holdt op (højst 30 dage efter, aldrig brugt samtidig), regnes som det samme tv. Deler de en adresse, er det sikkert; ellers kræves, at der kun er én mulig forgænger. Vises som "3 id'er – samme tv".
- **Sag** – status (blokeres, blokeret, undtagelse aftalt, afsluttet) og note pr. bruger (`sharing_users`).
- **Skæringsdato** – kolonnerne *Før* og *Efter*; brug fx datoen, hvor reglen blev lavet, for at se, om den virker.
- **Analysér / Hent historikken forfra** – første analyse efter en genstart henter hele historikken (et par minutter); derefter kun nye afspilninger.
- **Enhedstyper** (nederst) – hvordan hver platform/app er talt.

Det, der gemmes på disken, er kun dine egne afgørelser og sager. Historikken og resultatet ligger i hukommelsen.

## Nyt layout, forside og søgning (1.15.0)

**Udseende:** mørkt tema i Stream365-stilen (næsten sort, mintgrøn, skrifterne Outfit og DM Sans – de ligger i `app/static/fonts`, så siden henter intet udefra). Menuen står i venstre side, delt i grupper. På telefon er der en bundmenu (Overblik, Venteliste, Log, Kunder, Mere).

**Menuen:** Overblik · *Indhold:* Venteliste, Log, Regler, Premierer, Oversættelser · *Kunder:* Kontodeling · *Indsigt:* Statistik · *System:* Indstillinger, Opsætning. Et tal i menuen betyder, at noget venter: forslag på ventelisten, problemer med oversættelser, brugere der kan blokeres og nye premierer.

- **Overblik (ny forside):** "Kræver din handling" viser kun det, du skal gøre noget ved, og et tryk fører til det rigtige sted. Under det står dagens tal, det seneste, der er sendt til Sonarr/Radarr, og **Forbindelser** (svarer sonarr2, radarr, autobrr, Seerr, Tautulli, Tracearr, Oversætteren og Plex? – kun dem, der er sat op i `fangarr.env`). Siden opdateres hvert minut.
- **Hentet?** (Overblik, Log og Søgning): om en titel, Fangarr har tilføjet, er kommet hjem – *hentet*, *x af y udsendte afsnit hentet*, *henter*, *holdes tilbage (ventetid)*, *ikke udgivet endnu*, *ikke hentet endnu* eller *findes ikke længere*. Status hentes højst hvert 5. minut. Titlen er et link til Sonarr/Radarr. Adressen gættes ud fra Fangarrs egen (fangarr.domæne → sonarr2.domæne); passer det ikke, så sæt fx `SONARR2_LINK=https://…` i `fangarr.env`.
- **Log:** åbner på *Tilføjet*. Knapperne øverst skifter mellem beslutningerne.
- **Søg efter en titel** (feltet øverst): alt, Fangarr har gjort med en titel – tilføjelser, venteliste, log, oversættelser, koblinger og fjernede titler.
- **Fjern og husk** (Venteliste): fjerner titlen og husker den, så den ikke kommer på ventelisten igen ved næste udgivelse. *Fjern* virker som før. Fortryd under Indstillinger › Koblinger og fjernede titler › *Glem*. En husket titel bliver stadig tilføjet, hvis den senere findes på TheTVDB/TMDb og passer til en regel. Fjernede titler er med i eksporten.
- **Kontodeling husker historikken:** Tautullis historik gemmes i `data/kontodeling-historik.json.gz` og læses efter en genstart eller opdatering, så kun nye afspilninger hentes. Filen indeholder kundernes IP-adresser og enhedsnavne – den ligger kun i `data/` (ikke i git) og kommer med i Saltbox-backuppen af `/opt`. *Hent historikken forfra* erstatter filen.
- **Premierer:** kommende danske serier (3 uger) hentes i baggrunden hver 6. time. Tallet i menuen er dem, du ikke har set på siden endnu, og som hverken findes eller følges.
- **Statistik:** tryk på en kolonne for at sortere.
- **Oversættelser, Indstillinger og Opsætning** er delt i underfaner. *Test en titel*, *Prøv en regel* og *Filtre i autobrr* ligger under Opsætning.
- **Versionsnummer** nederst i menuen. Ligger der en nyere version på GitHub, står det der og på Overblik (tjekkes hver 3. time).

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
