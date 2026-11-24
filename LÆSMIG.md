# Fangarr

Fanger nye serier og film fra autobrr og lægger dem i Sonarr/Radarr ud fra dine egne regler.

- autobrr kalder `http://fangarr:8080/webhook/autobrr` (eksternt filter). Fangarr svarer 202 = stop.
- Fangarr slår titlen op (genrer, originalsprog, kanal, år, rating) og tjekker reglerne oppefra.
- Mangler TheTVDB/TMDb titlen endnu, kan den komme på **ventelisten** og prøves igen automatisk.

Menu (2.0): **Overblik** · *Indhold:* Log (Tilføjet · Alle beslutninger) · Venteliste (Venter · Godkendte koblinger · Fjernede titler · Indstillinger) · Oversættelser (Status · Venter · Problemer · Oversæt en titel · Indstillinger) · Bibliotek (statistik) · Regler (Regler · Afprøv en titel · Prøv på historikken · autobrr · Indstillinger) · *Kunder:* Kunder (Kundeliste · IPTV-linjer · Delte logins · Indstillinger) · Opkrævning (Opkrævning · Økonomi) · Beskeder (Skabeloner · Nyhed i opkrævningen) · Seerr-ønsker · Kontodeling · Guide (Besøg · Nyheder) · *System:* Drift (Forbindelser · Trackere) · Indstillinger (Telegram · Eksport og import · Apps og widget) · Hjælp.

Sikringer: prøvetilstand, loft pr. døgn, pladsgrænse, kun præcise titelmatch, Seerr-tjek, Telegram ved fejl og "i orden igen", dagligt resumé.

## Kunder og beskeder (2.2.0)
- **Beskeder › Send-kø** (`app/beskeder.py`): vælg skabelon og modtagere (alle aktive kunder, en tjeneste, en betalingsmetode – familie kun hvis valgt). Kunderne gennemgås én ad gangen med beskeden klar i Telegram eller Messenger (samme knapper som Send besked). Flueben ved sendt, og det kommer på tidslinjen. Køen kan stoppes og fortsættes.
- **Beskeder › Ønsker klar:** Fangarr spørger Seerr hvert 10. minut efter ønsker, der står som tilgængelige (film) eller hvor alle ønskede sæsoner er tilgængelige (serier). Seerr ser først titlen, når Plex viser den – og Plex viser den først med dansk tale eller tekst. Kunden findes via Plex-kontoen på kundekortet. Første gang huskes de gamle. Én besked om dagen til Stream365 Drift med antal (fra kl. `klar_hour`, standard 10) – aldrig navne, telefon eller e-mail.
- **Beskeder › Ændring for alle:** ny pris på en tjeneste fra en måned, evt. kun for kunder med en bestemt pris. Kontrolsiden viser hver kunde før og efter (pr. måned og pr. opkrævning); intet ændres før Bekræft. Prisen skiftes den 1. i måneden (før kundernes månedskørsel), og opkrævninger fra den måned, der hverken er anmodet eller betalt, regnes om. Opkrævninger før datoen røres ikke. Kan annulleres, indtil datoen er nået.
- **Beskeder › Skabeloner:** opkrævningsbeskeden som før + skabelonerne Velkomst, Dit ønske er klar, Prisændring og egne. Felter: `{fornavn} {navn} {guide} {titel} {tjeneste} {gammel_pris} {ny_pris} {dato}`.
- **Tidslinje på kundekortet:** bygges af det, Fangarr har gemt (oprettet, opkrævninger, anmodet, betalt, Seerr-ønsker) + nye hændelser (`k_events`: beskeder sendt, ønske klar, prisændringer) og noter.
- **Guide › Søgninger:** søgninger i guiden uden svar og de mest ønskede titler i Seerr (90 dage). **Guiden (`nyt-login/`) skal bygges igen** for at gemme antal svar pr. søgning (`h` i statistikfilen).
- Nye tabeller: `b_templates`, `b_queue`, `b_items`, `b_ready`, `b_price`, `k_events`. Ny indstilling: `klar_hour`. Ingen ændringer i `fangarr.env`.

## Påmindelser og knapper i Telegram (2.1.0)
- **Huskeliste** (Drift › Huskeliste, `app/huskeliste.py`): opgave, dato, server, valgfri kontrolkommando (med kopiknap), gentagelse. På dagen står den under *Kræver din handling*, og der kommer én besked i Stream365 Drift med **Udført** og **Udsæt en dag** (fra kl. `huske_hour`, standard 8). Datoopgaverne fra dokumentationen (24. nov.) lægges ind første gang.
- **Udgifter** (Opkrævning › Udgifter): navn, beløb pr. måned/år, næste fornyelse og varsel. Når varslet nås, kommer "Forny …" på huskelisten; Udført rykker fornyelsen en måned/et år frem. Økonomi bruger udgifterne – linjerne i det gamle felt "faste udgifter" flyttes over én gang.
- **Besked ved 0 streams** (Overblik, `app/stille.py`): Fangarr spørger Tautulli hvert minut og sender én besked, når ingen streamer (evt. kun i et tidsrum). Overblik viser, hvornår der normalt er stille om natten (0 streams i mindst 9 af 10 af de sidste 30 nætter).
- **Knapper i Stream365 Drift** (`app/tg.py`): Fangarr henter selv dine tryk hos Telegram (`getUpdates`, long polling) – ingen ny adresse udefra. Kun tryk fra `TELEGRAM_CHAT_ID` tages imod; andre afvises og tælles. Knappens data er kun et tal (`a:<id>`), handlingen ligger i tabellen `tg_actions`, kan kun udføres én gang og udløber efter 14 dage. Efter et tryk rettes beskeden med resultatet, og der kommer en **Fortryd**-knap, hvor det giver mening. Knapper på: manglende betaling (Betalt · +1 uge), forslag på ventelisten (Godkend · Fjern), nye danske premierer (Tilføj nu · Følg · Ikke interesseret), huskeliste (Udført · Udsæt en dag), 0 streams (Sig til igen), vist uden dansk tekst (Oversæt nu). Slås fra under Indstillinger › Telegram (så kommer beskederne uden knapper). **Kun én app må læse botten** – tjekket 24. nov. 2026.
- **Nye premierer** står under *Kræver din handling* med Ikke interesseret; første gang huskes de eksisterende, så der ikke kommer 20 beskeder på én gang.
- Nye indstillinger: `tg_buttons`, `huske_hour`, `prem_notify`, `prem_rule`. Nye tabeller: `huske`, `udgifter`, `tg_actions`. Ingen ændringer i `fangarr.env`.

## Ny menu og beskrivelser (2.0.0)
- **Menuen** har 14 punkter (se øverst). Indstillinger ligger hos den funktion, de hører til, som sidste underfane; siden Indstillinger har kun det, der gælder hele Fangarr. Telefonens bundmenu: Overblik · Kunder · Opkrævning · Log · Mere.
- **Fjernet:** siden Premierer (nye danske premierer står nu under *Kræver din handling* på Overblik med Tilføj nu/Følg), menupunktet Opsætning (nu underfaner under Regler), Import fra regneark, og "Senest sendt" og Forbindelser på Overblik (nu Log › Tilføjet og Drift › Forbindelser).
- **Gamle adresser** (`#setup`, `#iptv`, `#eco`, `#prem`, `#stats`, `#settings/gen` …) sendes videre til den nye plads.
- **Beskrivelser:** hver side har "Bruges til" og en fold-ud "Sådan bruger du siden"; hver underfane har én linje. Siden **Hjælp** (og ?-knappen øverst) viser alt på én side med søgefelt. Knapper har en forklaring ved musen over / langt tryk på telefonen. Alle tekster står i `app/static/js/hjaelp.js`.
- **Koden er delt op:** `app/static/index.html` (siderne), `app/static/fangarr.css` og én JavaScript-fil pr. menupunkt i `app/static/js/` (ingen byggeværktøj). `?v=__V__` i index.html bliver til versionsnummeret, så browseren henter filerne forfra efter en opdatering.
- **Test:** `pip install pytest` og `python -m pytest` (kører alle API-adresser mod en midlertidig testdatabase og efterlignede apps – rører aldrig den rigtige database). `python tests/demo.py` starter Fangarr med opdigtede testdata på port 18080, og `python tests/skaermbilleder.py <mappe>` tager skærmbilleder af alle sider (kræver playwright og Chrome). `tests/` kommer ikke med i Docker-billedet.

## Flere titler med samme navn og år (1.26.1)
Før blev en udgivelse sprunget over, når TMDb/TheTVDB havde flere titler med samme navn og år (fx "The Odyssey" 2026). Nu vælger Fangarr:
1. **den eneste, der allerede findes** i Sonarr/Radarr (film og serier), eller
2. **kun film:** den, der er **mindst 5 gange mere populær** hos TMDb (`popularity` fra Radarrs opslag) end nr. 2 – og mindst 1.
Ellers springes den stadig over. Valget står i loggen og i "Test en titel", fx "valgte den mest populære hos TMDb (The Odyssey, TMDb 1368337, popularitet 412 mod 3)". Gælder alle regler.

## 4K-udgaver: ekstra udgave til radarr4k (1.26.0)
Premierefilm i 4K med dansk tekst hentes automatisk til radarr4k – ved siden af 1080p-udgaven i den almindelige Radarr.

- **Instansen:** `ARR_INSTANCES=sonarr2,radarr,radarr4k` (radarr4k sidst) + `RADARR4K_URL`/`RADARR4K_APIKEY`. Navne, der ender på `4k`, er en "ekstra udgave" (`RADARR4K_EXTRA=true/false` overstyrer). De springes over i Oversættelser (søg og "På vej").
- **Regler med "Ekstra udgave":** udgivelsen behandles først af de almindelige regler (svaret til autobrr følger dem), og bagefter af reglerne med "Ekstra udgave" for sig. Ingen venteliste, intet Seerr-tjek og ingen hjælp til sonarr2 i den runde. Passer udgivelsen ikke (fx ikke 2160p), sker der intet og logges intet. Kommer en titel på ventelisten i den almindelige runde, prøves ekstra-reglerne også ved ventelistens forsøg – tilføjes filmen dér, søger radarr4k selv (autobrr har sendt udgivelsen for længe siden). Ventelistens afvisninger logges ikke for ekstra-reglerne.
- **Nye felter på reglen:** "Opløsning" (Alle / Kun 2160p – navnet skal indeholde 2160p, 4K eller UHD), "Udkommet inden for (måneder)" (tidligste dato hos TMDb: biograf, digital eller fysisk; fremtidige datoer tæller med; uden datoer tæller årstallet i år eller senere) og "Ekstra udgave".
- **Udeluk genrer:** på en ekstra-regel tilføjes filmen ikke, hvis TMDb mangler genrer (så "Animation" altid kan udelukkes).
- **Anbefalet regel "4K-premiere":** Film · radarr4k · skal indeholde `NORDiC, DKsubs, DANiSH` · Kun 2160p · udkommet inden for 12 mdr. · udeluk Animation · mappe `/mnt/unionfs/Media/Movies/4K` · profil "4K – dansk tekst" · hent når filmen er **Annonceret** (så film, der kommer før TMDb-datoen, ikke afvises) · mærke `4k-fangarr` · **Søg straks fra** (autobrr skubber udgivelsen) · Ekstra udgave.
- **autobrr:** det eksisterende Fangarr-filmfilter sender også 2160p-udgivelser (ingen opløsningsgrænse). DKsubs kommer med i filterets ord, når reglen har det – tryk "Opdatér filter" under autobrr-fanen. Skub til radarr4k sker med et almindeligt autobrr-filter ("Film4K", prioritet 0, 2160p, klient radarr4k) – oprettes i autobrr.
- **Plex:** radarr4k › Connect › Webhook → `http://fangarr:8080/webhook/import` (On File Import + On File Upgrade). Fangarr beder Plex scanne netop filmens mappe med det samme og igen efter 2 og 10 minutter. "Test" i radarr4k svarer `{"ok": true, "test": true}`. Fejler alle tre forsøg: én besked til Telegram, og "i orden igen", når det virker. Kræver `PLEX_URL`/`PLEX_TOKEN`.

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

## Hentegrænse: afviste afsnit søges igen (1.22.0 – 1.22.1)
Superbits afviser hentninger, når der hentes mange torrents på kort tid. Det sker, når sonarr2 henter mange enkeltafsnit på én gang – fx når en bruger ønsker flere sæsoner i Seerr (Hell's Kitchen 20. nov. 2026: fem afsnit gik igennem, resten blev afvist). sonarr2 skriver "API Grab Limit reached" og "Couldn't add release … to download queue" i sin log og prøver aldrig igen, så afsnittene bliver stående som manglende.

- **Hvert 2. minut** læser Fangarr sonarr2's log (advarsler og fejl), finder de afviste udgivelser og slår serie og afsnit op ud fra navnet. Kun afsnit, der er overvågede og mangler en fil, kommer med (tabellen `grab_retry`).
- **Seriens øvrige manglende afsnit tages med (1.22.1):** efter en afvisning sætter sonarr2 trackeren på pause og søger resten af serien uden den ("1 active indexers" i loggen). De afsnit bliver hverken fundet eller afvist, og der står ingen fejl – sådan forsvandt Hell's Kitchen sæson 25. Derfor lægger Fangarr også seriens andre afsnit på listen, når de er overvågede, mangler en fil og allerede er sendt (ikke specials). Sker én gang pr. sag; kolonnen `kind` i `grab_retry` viser `afvist` eller `ekstra`.
- **Én besked pr. serie** til Telegram: hvilke afsnit der blev afvist, og at Fangarr søger dem igen.
- **Ny søgning i portioner:** 3 afsnit hvert 10. minut (`EpisodeSearch` i sonarr2). Fangarr henter ikke selv noget – sonarr2's egne regler (profil, ventetid, point) gælder. Afsnit, der er kommet hjem, ligger i køen eller ikke længere er overvågede, røres ikke.
- **"I orden igen"**, når alle afsnit er hjemme. Mangler nogle stadig efter 24 timer, giver Fangarr op og skriver, hvilke der skal søges i hånden.
- Første gang læses loggen 48 timer tilbage, så afvisninger fra før opdateringen kommer med. Derefter kun nye linjer (`grab_seen` i `kv`).
- Status og samme forklaring står under **Indstillinger › Hentegrænse hos trackeren**. Alt står også i Fangarrs log (`hentegrænse`).
- Valgfrit i `fangarr.env`: `GRAB_RETRY=false` (slå fra), `GRAB_RETRY_BATCH`, `GRAB_RETRY_MINUTES`, `GRAB_RETRY_HOURS`, `GRAB_LOOKBACK_HOURS`. Kun sonarr2 – ikke Radarr.
- Tilbage til 1.21.0: tabellen `grab_retry` gør ingen skade i den gamle version.

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

## Køb i guiden – "Få flere ønsker" (1.25.0)
Kunden vælger selv pakke, skifter, stopper eller køber enkelte film og sæsoner i guiden. Koden ligger i `app/kob.py` (adresserne til guiden) og i `app/static/nyhed-vis.js` (arket kunden ser). Reglerne er de samme som på kundekortet (`app/oensker.py`).

- **Slås til** under Kunder › Seerr-ønsker › Indstillinger › **Køb i guiden**. Det er kun åbent, når styringen af Seerr står på **Til**, og nøglen er sat op (se nedenfor). Lukket = ingen knap i guiden, og nyheder med knappen "Få flere ønsker" vises uden knap.
- **Hvor kunden finder det:** en boks med knappen **Se dine ønsker** øverst i guidens afsnit om Seerr (vælg afsnittet under indstillingerne, eller lad Fangarr finde det), og som knap på en nyhed (Guide › Nyheder › Knappen › Åbner "Få flere ønsker").
- **Arket:** kundens pakke, planlagte skift og købte ønsker tilbage · fanen **Pakke hver måned** (de fire pakker med pris pr. måned og pr. periode, "Din pakke", "Anbefalet" på Populær, "Ingen pakke" for at stoppe) · fanen **Enkeltkøb** (film og sæsoner med − og +, op til 30 af hver ad gangen) · beløbene og næste betaling, før kunden bekræfter · kvittering med **Åbn Seerr**. Familie (type Egen) får beskeden "Du kan ønske alt, du vil – gratis". Ukendte, stoppede og kunder uden næste betaling bliver bedt om at skrive til dig (Messenger/Telegram-knapperne fra Guide › Nyheder, hvis de er sat).
- **Regler:** større pakke virker med det samme med tillæg pr. dag til næste betaling; mindre pakke eller stop fra næste betaling (kan fortrydes); enkeltkøb lægges på næste betaling og udløber aldrig. Har prisen ændret sig, siden kunden åbnede arket, afvises valget, og den nye pris vises. Højst 8 valg pr. kunde pr. 10 minutter.
- **Beskeder:** hvert valg giver en besked til Stream365 Drift, fx "🛒 Køb i guiden: Bo Bundgaard valgte Populær – tillæg 4 kr. Næste betaling 28. november: 143 kr." (navn og beløb – aldrig telefon eller e-mail), en linje i Seerr-ønsker-loggen med "(guiden)" og i Fangarrs log.
- **Sådan taler guiden med Fangarr:** `nyt` kalder `POST http://fangarr:8080/api/kob/mig`, `/tilbud` og `/vaelg` inde i Docker-netværket med headeren `X-Nyt-Token`. Fangarr kender nøglen fra **`NYT_TOKEN`** i `fangarr.env` (mindst 32 tegn); guiden læser den fra filen **`/opt/nyt/data/fangarr_token`** (chmod 600). Uden (rigtig) nøgle svarer adresserne 404. Guiden sender kun Plex-id og brugernavn på den kunde, der er logget ind – aldrig hvad browseren påstår. Fangarr sender kun kundens egne ønsker, pakke og næste betaling tilbage. Udefra ligger adresserne bag Authelia som resten af Fangarr.
- **Skift nøglen:** slet linjen `NYT_TOKEN=…` i `fangarr.env`, lav en ny med `openssl rand -hex 24`, skriv den samme nøgle i `/opt/nyt/data/fangarr_token`, og kør `cd /opt/fangarr && docker compose up -d --force-recreate`. Nøglen må aldrig stå i chatten eller dokumentationen.

## Nyheder i guiden (1.24.0)
Det farvede kort øverst på **guide.stream365.vip** – til tilbud, nyheder og vigtige beskeder – og nyhedens pop-up. Skrives under **Guide › Nyheder**. Koden ligger i `app/nyheder.py` (data i tabellen `g_news`) og `app/static/nyhed-vis.js` (tegningen af kort og pop-up).

- **Sådan kommer nyhederne ud:** guiden (appen `nyt`) henter selv de udgivne nyheder hos Fangarr hvert 30. sekund inde i Docker-netværket (`POST http://fangarr:8080/api/nyheder/guide`). **Ingen ændringer i docker-compose-filerne.** Guiden gemmer seneste svar i `/opt/nyt/data/nyheder.json`, så kortet vises, selv om Fangarr genstarter. Guidens `index.html` røres ikke.
- **Samme tegning to steder:** Fangarr sender `nyhed-vis.js` med til guiden. Forhåndsvisningen i Fangarr bruger den samme fil, så det, du ser, er præcis det, kunderne ser. Ændres udseendet, er det nok at opdatere Fangarr.
- **Skabeloner:** Tilbud, Nyhed, Jul og Vigtig besked (farver + en eksempeltekst, der kun skiftes, hvis du ikke har skrevet din egen). **Illustrationer:** billet med din egen tekst, gave, julekalender, ny række, Seerr-ønske, danske tekster, download, film og vigtig besked – tegnet af Fangarr i skabelonens farver. Upload af egne billeder findes ikke endnu.
- **Kortet:** mærkat, overskrift, kort tekst, illustration, nedtælling til slutdatoen (valgfri), kryds til at lukke (huskes på enheden), "Gælder til …" ved Tilbud. Flere aktive nyheder: kunden bladrer med pile, prikker eller ved at stryge.
- **Knappen:** åbner nyhedens pop-up · fører til et afsnit i guiden (siden glider derned, og afsnittet lyser kort op) · åbner "Få flere ønsker" (fra 1.25.0, se Køb i guiden) · ingen knap. Listen over afsnit sender guiden selv med (`<section id>` + overskriften). Forsvinder et afsnit fra guiden, står der en advarsel i nyhedslisten.
- **Pop-up'en:** overskrift, pris med tekst under, indledning, op til 8 trin (med valgfri illustration), "Læs også"-link til et afsnit, knappen nederst (lukker) og **Skriv til os på Messenger/Telegram**. Kontaktknapperne vises kun, når der står links under Guide › Nyheder › Indstillinger. Telefon: glider op nedefra (luk med kryds, knappen, ved at trække ned eller med telefonens tilbage-knap). Computer: vindue i midten (også Escape).
- **Hvornår:** "Vises fra" og "Vises til" (dansk tid). Guiden viser selv nyheden fra start til slut, også hvis Fangarr er nede. **Kun for nye brugere:** de første 14 dage (kan rettes) efter kunden accepterede reglerne i guiden.
- **Status i listen:** Kladde · Planlagt · Aktiv · Udløbet. **Udgiv** kræver overskrift, knaptekst, afsnit (hvis knappen fører til et), startdato, slutdato ved nedtælling og indhold i pop-up'en. **Skjul for kunderne** gør nyheden til en kladde igen. Rækkefølgen (pilene) er den rækkefølge, kunderne bladrer i.
- **Set og tryk:** guidens tæller gemmer hændelsen `news` (set i 1 sek., tryk på knappen, pop-up åbnet, Skriv til os, lukket) med Plex-id – samme filer og regler som fanen Guide (ingen IP-adresser, slettes efter 90 dage, din egen konto tælles ikke). Listen viser antal forskellige brugere. Kræver `/guide-stat` som fanen Besøg.
- **Sikkerhed:** adressen `/api/nyheder/guide` svarer kun med udgivne nyheder og ingen kundedata. Udefra ligger den bag Authelia som resten af Fangarr. Tekster escapes altid; der kan ikke skrives HTML i nyhederne. Kontaktlinks skal begynde med `https://`.

## Seerr-ønsker: pakker, enkeltkøb og hvem der må ønske (1.23.0)
Ingen gratis ønsker i Seerr fra 21. nov. 2026: kun kunder med en **pakke** eller **købte ønsker** – og **familie** (type Egen på kundekortet) – må ønske. Fangarr styrer det selv ud fra Kunder. Koden ligger i `app/oensker.py`, data i tabellerne `s_*` i `data/fangarr.db`. Kræver `SEERR_URL`/`SEERR_APIKEY` (de samme som Seerr-tjekket) – ingen nye linjer i `fangarr.env`.

- **Kundekortet › Seerr-ønsker:** pr. Plex-konto: pakke, købte ønsker tilbage, hvad kontoen kan i Seerr nu og har brugt de sidste 30 dage. Knapperne **Vælg/Skift pakke** og **Køb ønsker** viser, hvad der lægges på næste betaling, før der gemmes. Et køb kan fortrydes, så længe ønskerne ikke er brugt, og beløbet ikke er anmodet.
- **Pakker** (pr. 30 dage, kan rettes under Indstillinger): Lille 9 kr. = 3 film · Populær 19 kr. = 5 film + 2 sæsoner · Stor 39 kr. = 17 + 9 · Maks 59 kr. = 29 + 13. Pakken er tjenesten **Ekstra ønsker** på kundekortet og betales med kundens egen cyklus.
  - **Ny eller større pakke:** virker med det samme. Næste betaling får et tillæg for dagene indtil da (forskellen i månedspris × dage ÷ 30, rundet til hele kroner).
  - **Mindre pakke eller stop:** gælder fra næste betaling. Er næste opkrævning allerede lavet (og ikke anmodet), rettes den med det samme; ellers kommer ændringen med, når den laves. Seerr beholder den gamle pakke til betalingsdatoen. Vælg den nuværende pakke igen for at fortryde.
- **Enkeltkøb:** 5 kr. pr. film og 10 kr. pr. sæson (Indstillinger). Et tillæg på næste betaling. Købte ønsker kommer oveni pakken og **udløber aldrig**. Fangarr ser i Seerr, hvornår de bruges: et ønske, pakken ikke dækker, bruger et købt ønske, og grænsen holdes oppe, til ønsket er 30 dage gammelt (ellers ville pakkens ønsker blive spærret bagefter). Ønsker fra før første køb bruger aldrig købte ønsker.
- **Tillæg og ændringer på opkrævningen:** "Næste betaling" er den første opkrævning, der hverken er anmodet, betalt eller sprunget over og har betalingsdato i dag eller senere – ellers den næste måned i kundens cyklus. Findes den, lægges tillægget direkte på den (og den regnes om); ellers venter tillægget i Fradrag og tillæg til næste opkrævning. Teksten står i beskeden til kunden, fx "Enkeltkøb i Seerr: 2 film og 1 sæson: +20 kr.".
- **Seerr:** Fangarr giver rettigheden **Anmod** (eller kun "Anmod film"/"Anmod serier", fx ved Lille) og sætter brugerens egen grænse pr. 30 dage = pakke + købte ønsker i brug. Uden ønsker fjernes rettigheden. **Grænsen 0 betyder "ubegrænset" i Seerr** – Fangarr giver derfor aldrig en kunde 0; kun familie får ubegrænset. Auto-anmod (huskelisten ønsker automatisk) fjernes for kunder. Seerr-brugere uden kunde i Fangarr, og stoppede kunder, kan ikke ønske. Brugernavne og øvrige indstillinger i Seerr bevares (Fangarr henter brugerens indstillinger og sender dem tilbage med de nye grænser).
- **Rør aldrig:** admin, brugere med "Administrer brugere" og Seerr-bruger-id'erne under Indstillinger › **Rør ikke** (fx dine egne konti).
- **Tilstand** (Kunder › Seerr-ønsker): **Fra**, **Prøvetilstand** (standard – viser kun, hvad Fangarr ville ændre) og **Til**. Fangarr gennemgår Seerr hvert 5. minut og lige efter en ændring på kundekortet.
- **Bremse:** mister flere end 5 (Indstillinger) retten til at ønske på én gang, fjerner Fangarr ingen og giver besked.
- **Gamle tjenester "Ekstra ønsker"** uden pakke genkendes automatisk, når prisen passer til én pakke, og kunden har én Plex-konto. Ellers står de på siden som noget, du skal afgøre: vælg pakken på kundekortet ud for den rigtige konto – den gamle tjeneste bliver til pakken (ingen ny tjeneste, intet tillæg, når pakken ikke koster mere end tjenesten). Slettes eller slås tjenesten fra på kundekortet, er pakken stoppet.
- **Siden Kunder › Seerr-ønsker:** tilstand, ændringerne (i prøvetilstand: det, Fangarr ville gøre), hvem der kan ønske nu og hvorfor, pakker og købte ønsker, familie, indstillinger og log. Forsiden viser problemer og ventende ændringer i prøvetilstand.
- **Telegram (Stream365 Drift):** kun ved problemer og "i orden igen": Seerr svarer ikke (3 gange i træk), bremsen, ændringer Seerr ikke ville gemme.

## Kunder og betalinger (1.16.0)
Fire nye sider under **Kunder** i menuen. Koden ligger i `app/kunder.py`, data i de nye tabeller `k_*` i `data/fangarr.db`.

- **Opkrævning:** månedens liste laves af sig selv ud fra kundernes cyklus (månedlig, kvartal 1/4/7/10 · 2/5/8/11 · 3/6/9/12, halvårlig, årlig). Beløb = kundens tjenester pr. måned × antal måneder + fradrag/tillæg. Knapper: Send besked (fra 1.19.0, før Kopiér besked), Anmodet, Betalt, Ret (beløb, note, spring over, regn om).
- **Kunder:** kundeliste med søgning, kundekort (betaling, tjenester med pris, fradrag og tillæg, IPTV-linjer, opkrævninger), Delte logins, Import fra regneark og Indstillinger. Én kunde kan betale for flere konti. "Flet ind i anden kunde" flytter en konto over til den, der betaler.
- **IPTV-linjer:** alle linjer med udløbsdato, pris og knappen Fornyet.
- **Økonomi:** betalt/ventet indtægt pr. måned mod IPTV-fornyelser og faste udgifter.
- **Synk fra Tautulli:** henter Plex-brugerne (`get_users` + `get_users_table`) med knappen og hver nat (kl. 3 som standard – først efter første manuelle synk). Brugere kobles til en kunde via brugernavn, e-mail eller navn (Tautullis "friendly name"). En ukendt Plex-bruger bliver oprettet som kunde uden cyklus og står under "Mangler opsætning". Kræver `TAUTULLI_URL`/`TAUTULLI_APIKEY` (samme som Kontodeling).
- **Beskeder på Telegram (Stream365 Drift):** den 1. i måneden (antal kunder og beløb, antal IPTV-linjer der skal fornyes), og når nogen har stået som Anmodet i mere end 7 dage (derefter højst én samlet påmindelse om ugen, og "alle har betalt"). Fangarr skriver aldrig til kunderne og spærrer ingen.
- **Kodeord og IPTV-koder** gemmes i databasen, fordi de skal kunne slås op samme sted. De sendes kun til browseren, når der trykkes **Vis** (`/api/kunder/secret/...`), og står aldrig i lister, log, Telegram, CSV-eksporten eller Fangarrs JSON-eksport. Fangarr skal derfor blive bag Authelia, og `data/` må aldrig i git.
- **Import fra regneark** blev fjernet i 2.0 (engangsfunktion, brugt 13. nov. 2026).
- Kundedata er **ikke** med i Fangarrs eksport/import af regler. De ligger i `data/fangarr.db`, som kommer med i serverens backup af `/opt`. Kundelisten uden koder kan hentes som CSV under Kunder › Indstillinger.

### Betalingsdato (1.16.2)
- **Betalingsdatoen** er kundens faste dato i måneden (kundekortet › Fast dato i måneden). Kunder uden fast dato regnes som den 1. En dato, måneden ikke har (fx 31.), bliver til månedens sidste dag.
- **Opkrævning:** sortér efter Navn eller Betalingsdato (valget huskes i browseren). Ved sortering efter dato vises en overskrift pr. dato med antal og beløb. Filteret **I dag** viser dem, der har betalingsdato i dag.
- **Telegram på dagen** (kl. 8, samme klokkeslæt som de andre beskeder): navn, beløb og betalingsmetode for dem, der har betalingsdato i dag og endnu ikke er anmodet, betalt eller sprunget over. Ingen besked, når ingen skal opkræves. Beskeden den 1. med månedens overblik sendes stadig. Navne står i beskeden – aldrig telefonnumre eller koder.

## Roligere alarmer om Sonarr/Radarr (1.19.3)
Natten til 16. nov. 2026 kom der mange beskeder "sonarr2: kan ikke nås (ReadTimeout)" efterfulgt af "i orden igen". sonarr2 var ikke nede: det var opslag hos SkyHook (TheTVDB), der tog over 30 sekunder. Hver fejl i Fangarr blev fulgt 70 sekunder senere af "SkyHookProxy … Http request timed out" i sonarr2's log.

- Et **opslag** (`/lookup`), der tager over 30 sekunder eller giver 5xx, giver ingen alarm. Det står i Docker-loggen ("opslag tog over 30 sekunder – TheTVDB/TMDb er langsom"), og titlen prøves igen fra ventelisten som før.
- **"Har ikke svaret i X minutter"** kommer først, når Sonarr/Radarr ikke har svaret i 5 minutter i træk (`DOWN_ALARM_SECONDS=300`, kan ændres i `fangarr.env`). Ét langsomt svar står kun i Docker-loggen.
- "I orden igen" kommer kun, når der har været en alarm.
- Andre fejl (4xx/5xx på andet end opslag) giver alarm med det samme som før.

## Send besked fra Opkrævning (1.19.0)
Knappen **Send besked** ved hver kunde under Opkrævning afløser Kopiér besked. Den viser beskeden til kunden og åbner chatten med beskeden klar. Du trykker stadig selv send i appen – Fangarr skriver aldrig selv til kunderne.

- **Telegram:** *Åbn i Telegram* åbner chatten med kunden med beskeden skrevet i feltet (`https://t.me/<brugernavn>?text=…`). Kræver kundens Telegram-brugernavn (eller et synligt telefonnummer) på kundekortet.
- **Messenger:** *Kopiér + åbn Messenger* kopierer beskeden og åbner chatten (`https://m.me/<brugernavn>`). Messenger kan ikke få teksten sat ind via et link til en privat profil, så den sættes ind med fingeren. Kræver kundens Messenger-brugernavn på kundekortet (det, der står efter `facebook.com/`).
- **1.19.1:** på Android åbnes apperne direkte i stedet for hjemmesiden i browseren: Telegram med `tg://resolve?domain=…&text=…`, Messenger med en intent-adresse til appen `com.facebook.orca` (med m.me som nødløsning, hvis appen mangler). På computer bruges stadig t.me og m.me.
- **1.19.2:** Messenger-knappen peger ikke længere på den officielle app (`com.facebook.orca`) – patchede udgaver har et andet pakkenavn, og så sendte Android brugeren til Play Butik. Uden pakkenavn åbner Android den app, der må åbne m.me-links, ellers browseren. Pakkenavnene kan skrives under Kunder › Indstillinger (valgfrit), så knapperne åbner præcis den app.
- **Del …** åbner telefonens delemenu (vælg app og kunde, teksten står klar). **Kopiér** kopierer kun.
- Alle fire knapper sætter kunden til **Anmodet**. Fortrydes under Ret › Fortryd Anmodet.
- **Kontakt via** på kundekortet (FB/TG) bestemmer, hvilken app der åbnes. Er feltet tomt, bruges det brugernavn, der er udfyldt.
- **Tre måder at anmode på**, hver med sin tekst på linjen `{betaling}` (rettes under Kunder › Indstillinger):
  - Revolut med **betalingslink**: linket indsættes i Send besked og sættes ind ved `{link}`. Der kan ikke sendes uden et link, der begynder med `https://`.
  - Revolut **direkte i appen** og **MobilePay**: kunden får bare besked om, at der er anmodet.
  - Valget for en Revolut-kunde huskes på kundekortet ("Revolut: sådan anmoder du").
- **Rabatter og tillæg** flettes ind med `{rabatter}` – én linje pr. fradrag/tillæg på opkrævningen med den tekst, der er skrevet på kunden (fx "🎁 Rabat som ny kunde: -60 kr."). Uden tekst står der Rabat eller Tillæg.
- **Nyhed til kunderne** (kortet øverst i Opkrævning) flettes ind med `{nyhed}`. Hver kunde får den én gang, med sin næste opkrævning, og den bliver stående, til den fjernes. *Gem* retter teksten uden at sende den igen; *Send til alle igen* starter forfra. Sletter du nyheden fra en enkelt besked, før du sender, har kunden den stadig til gode.
- Beskeden kan rettes i Send besked, før den sendes (gælder kun den ene besked).
- En linje i skabelonen, der kun består af `{rabatter}`, `{betaling}` eller `{nyhed}`, forsvinder, når feltet er tomt. Den gamle standardskabelon skiftes selv ud med den nye; en skabelon, du selv har rettet, bevares, og Indstillinger advarer, hvis de nye felter mangler.
- **Databasen:** nye kolonner `tg`, `fb`, `revolut` på `k_customers` og `pay_link`, `news_id`, `sent_at` på `k_charges` (oprettes selv ved start). Nyheden ligger i `kv` under `kunder_news`. Betalingslinket gemmes kun i databasen og skrives aldrig i loggen eller i Telegram.
- Tilbage til 1.18.0: de nye kolonner gør ingen skade i den gamle version.

### Frist, periode og næste opkrævning i beskeden (1.21.0)
Fire nye felter til beskedskabelonen (Kunder › Indstillinger), så kunden kan se, hvornår der skal betales, hvad betalingen dækker, og hvornår den næste kommer:

- `{frist}` – seneste betalingsdato: den dag, beskeden sendes, plus **Kundens frist for at betale (dage)** (ny indstilling, 7 som standard). Før beskeden er sendt, tælles der fra i dag; når den er sendt, står fristen fast, også ved Send igen. Fristen ligger aldrig før kundens faste betalingsdato. Årstallet skrives kun med, når fristen ligger i et andet år.
- `{periode}` – hvad betalingen dækker: fra betalingsdatoen til dagen før næste betalingsdato. Kunder uden fast dato (den 1.) får hele måneder ("november 2026 – januar 2027"), kunder med fast dato får datoer ("25. november 2026 – 24. februar 2027").
- `{næste}` – datoen for næste opkrævning (betalingsdatoen i den næste måned i kundens rul). Bliver beløbet et andet end denne gang – en rabat udløber, eller prisen er ændret på kundekortet – står det forventede beløb i parentes: "25. februar 2027 (forventet 600 kr.)". Det forventede beløb er kundens nuværende priser plus de fradrag/tillæg, der har gange tilbage.
- `{antal_måneder}` – "1 måned", "3 måneder", "6 måneder" eller "12 måneder".
- Standardskabelonen bruger de nye felter og skriver "540 kr. for 3 måneder" i stedet for "(Kvartal • Cyklus: 2/5/8/11)". Den gamle standardskabelon skiftes selv ud; en skabelon, du selv har rettet, bevares. `{frekvens}` og `{cyklus}` virker stadig.
- Ingen ændring i databasen eller i `fangarr.env`.

## Guide – hvem har været inde på guide.stream365.vip? (1.18.0)
Fanen **Guide** (under Kunder) viser, hvem der har været inde på guiden, hvornår, hvilke afsnit de har læst, og hvad de har søgt efter – med rigtige navne fra Kunder (Tautulli).
- **Tallene kommer fra appen `nyt`** (mappen `nyt-login/`), som skriver én fil pr. dag i `/opt/nyt/data/statistik/`. Fangarr læser kun – den ændrer intet i guiden og sender ingen beskeder. Se `nyt-login/LÆSMIG.md` › Tæller.
- **Opsætning (én gang):** tilføj linjen `- "/opt/nyt/data/statistik:/guide-stat:ro"` under `volumes:` i `/opt/fangarr/docker-compose.yml`, og kør `cd /opt/fangarr && docker compose up -d`. Indtil da viser fanen, hvad der mangler. Mappen kan ændres med `GUIDE_STAT_DIR` i `fangarr.env`.
- **Kortene øverst:** hvor mange der har været inde i perioden (7, 30 eller 90 dage), antal besøg, hvor mange der har accepteret reglerne ud af de aktive kunder med Plex, og hvor mange aktive kunder der aldrig har været inde.
- **Hvem har været inde:** én linje pr. bruger med seneste besøg og antal. **Vis** folder brugerens læste afsnit og søgninger ud.
- **Mest læste afsnit** og **Søgeord:** samlet for alle – viser, hvad kunderne bruger guiden til, og hvad de leder efter uden at finde.
- **Nederst:** dem, der har accepteret reglerne uden at have været inde i perioden, og aktive kunder, der aldrig har været inde (hvis du vil minde nogen om guiden).
- Din egen konto (`STAT_EXCLUDE` i `/opt/nyt/docker-compose.yml`, standard Stream365) tælles ikke. Ingen IP-adresser gemmes, og alt ældre end 90 dage slettes af `nyt`.
- En bruger mærket **ukendt i Kunder** har en Plex-konto, Fangarr ikke kender – tryk "Synk fra Tautulli" under Kunder.

## Kom det faktisk i Plex? (1.17.0)
- Kræver Oversætteren med trin C5 (`REVEAL_VERIFY=true`, standard). Før blev Plex kun bedt om at scanne én gang. Kunne Plex' server endnu ikke se den nye mappe, fandt scanningen ingenting, og filmen kom aldrig i Plex, selvom den stod som vist (fem NORDiC-film 9.–14. nov. 2026).
- Oversætteren tjekker nu selv efter 2 minutter og beder Plex scanne igen, hvis filen mangler (igen efter 5, 15 og 60 minutter, derefter hver time i et døgn).
- **Vist i Plex** viser under hver titel, om Plex har bekræftet den ("i Plex", evt. "efter 2 ekstra scanninger"). Ældre rækker fra før trinnet har ingen linje.
- Mangler en titel stadig efter ca. en time, står den øverst under **Skjult for kunderne** med ⚠, og der sendes én Telegram-besked ("ikke kommet i Plex") – og én, når den er kommet ind ("i orden igen"). Fangarr husker, hvad der er meldt (tabellen `plex_missing_notified`).
- **1.17.1:** "se listen" på kortene Problemer og Skjult for kunderne (Oversættelser › Status) åbner nu den rigtige underfane. Linkene pegede på lister, der siden 1.15.0 ligger på skjulte underfaner, så der skete ingenting.

## Apps med lampe og widget på telefonen (1.20.0)
Forsiden har fået kortet **Apps**: alle dine server-apps i grupper med lampe (Oppe · Tjekker igen · Nede · Vedligehold · Ingen lampe). Tryk på en app for at åbne den. Er en app nede, står den også under **Kræver din handling**. Koden ligger i `app/apps.py`.

- **Listen kommer fra Uptime Kuma**, statussiden `apps` (hentes internt på `http://uptime:3001`, højst hvert 30. sekund). Grupper og rækkefølge på statussiden er grupper og rækkefølge i Fangarr. **Ny app:** opret monitoren i Uptime Kuma, og læg den på statussiden – så dukker den selv op. Fangarr ændrer intet i Uptime Kuma og sender ingen beskeder herfra.
- **Appens adresse gættes ud fra monitorens navn** ("WUD feeder" → `https://wud-feeder.<domæne>`). Passer gættet ikke, rettes det under **Indstillinger › Apps og widget** (`Navn = adresse`). Samme sted tilføjes apps uden monitor (`Gruppe | Navn | adresse`); de får et felt uden lampe.
- **"Tjekker igen"** betyder, at et tjek er fejlet, og Uptime Kuma prøver igen, før den melder appen nede.
- Svarer Uptime Kuma ikke, bliver felterne stående med "Ukendt".

### Widget-adressen `/widget/<nøgle>`
Til en widget på telefonens hjemmeskærm (KWGT). Svarer med en flad liste: `.apps[N].n` (navn), `.g` (gruppe), `.s` (up/down/pending/maint/unknown/none), `.t` (tekst), `.c` (farve) og `.u` (appens adresse), plus `.head` ("Alt kører" / "Scrutiny er nede"), `.headc`, `.down`, `.total` og `.at` (klokkeslæt). Fra 1.20.1 også `.h` (gruppens navn på gruppens første app, ellers tom) og `.b` (feltets baggrundsfarve), og med `?pad=30` efter nøglen fyldes listen op til 30 med tomme, gennemsigtige felter, så en widget med et fast antal felter altid får svar. Fra 1.20.2: `.i` (to bogstaver til appens mærke), `.k`/`.kt` (gruppens farve: mærkets baggrund og tekst), gruppeoverskriften `.h` står med almindelige bogstaver, og med `&cols=4` begynder hver gruppe på en ny række.

- **Det er den eneste adresse i Fangarr, der åbnes uden om Authelia.** Den viser kun appnavne, grupper, oppe/nede og adresser – ingen kunder og ingen tal – og kan ikke ændre noget.
- Den findes kun, når `WIDGET_KEY` i `fangarr.env` er på mindst 32 tegn. Forkert nøgle giver 404 (samme svar som en adresse, der ikke findes), og efter 20 forkerte forsøg på et minut lukkes der i et minut.
- **Lav nøglen på feeder uden at vise den** (gør intet, hvis linjen findes i forvejen):
  ```
  grep -q '^WIDGET_KEY=' /opt/fangarr/fangarr.env || echo "WIDGET_KEY=$(openssl rand -hex 24)" >> /opt/fangarr/fangarr.env
  ```
- **Skift nøglen** (fx mistet telefon): slet linjen `WIDGET_KEY=…` i `fangarr.env`, kør kommandoen igen og `docker compose up -d --force-recreate`. Den gamle adresse virker ikke længere.
- **Traefik:** `docker-compose.yml` på feeder skal have en ekstra regel (router) kun for stien `/widget/` uden Authelia; resten af Fangarr bliver bag Authelia. Linjerne afhænger af filen på serveren – se projektets `claude/hjemmeskaerm-widget.md`.
- Nøglen må aldrig stå i chatten eller dokumentationen. Den ligger kun i `fangarr.env` og i widgetten.

## Filer
- `app/main.py` – server (FastAPI) · `app/apps.py` – Apps og widget · `app/hentegraense.py` – afviste afsnit søges igen · `app/kunder.py` – Kunder og betalinger · `app/oensker.py` – Seerr-ønsker · `app/nyheder.py` + `app/static/nyhed-vis.js` – Nyheder i guiden · `app/kob.py` – Køb i guiden · `app/static/index.html` + `app/static/fangarr.css` + `app/static/js/*.js` – interface (teksterne i `js/hjaelp.js`) · `app/VERSION` · `tests/` – testsuite, efterlignede apps og skærmbilleder
- `fangarr.env.eksempel` – skabelon til `fangarr.env` (API-nøgler). `chmod 600`. **Kommer aldrig i git.**
- Data: `/opt/fangarr/data/fangarr.db`. Natlige eksportfiler: `/opt/fangarr/data/backup/`.
- `docker-compose.yml` laves af Saltbox og ligger kun på serveren.

## Opdatering
```
cd /opt/fangarr && ./opdater.sh
```
Log: `docker logs --tail 50 fangarr`
