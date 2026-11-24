// Hjælp (2.0): ALLE beskrivelser i Fangarr står her, så siderne og siden Hjælp altid viser det samme.
// Hver side: navn, gruppe, "Bruges til" (én linje) og "Sådan bruger du siden" (3–6 punkter).
// Hver underfane: "Bruges til" (én linje). Nye funktioner får deres tekst her i samme version.
// Knapper: KNAP herunder giver en forklaring, når musen holdes over knappen, eller ved langt tryk på telefonen.

const HJ = {
  home: {navn: "Overblik", gruppe: "", bruges: "Det, du skal gøre noget ved, apps med lampe og dagens tal.",
    saadan: [
      "<b>Kræver din handling</b> er din huskeliste: betalinger, der mangler, forslag på ventelisten, oversættelser, der er gået galt, nye premierer, apps, der er nede, og meget mere. Tryk på en linje for at gå direkte til stedet.",
      "Står der intet under Kræver din handling, er der intet at gøre.",
      "Opgaver fra <b>huskelisten</b> (Drift › Huskeliste) står her på dagen. Nye danske premierer står her med <b>Tilføj nu</b>, <b>Følg</b> og <b>Ikke interesseret</b>.",
      "<b>Besked ved 0 streams</b>: tryk <b>Sig til ved 0 streams</b>, før du skal gøre noget, der afbryder kundernes streaming. Fangarr spørger Tautulli hvert minut og sender én besked til Stream365 Drift, når ingen streamer – evt. kun i et tidsrum, du vælger. Under knappen står, hvornår der normalt er stille om natten.",
      "<b>Apps</b> viser alle dine apps med lampe fra Uptime Kuma. Tryk på en app for at åbne den.",
      "Nederst står dagens tal: hvad Fangarr har tilføjet, diskpladsen og hvad der venter.",
      "Siden opdateres af sig selv hvert minut. Tallet ved Overblik i menuen er antallet af ting, der kræver din handling.",
    ]},
  log: {navn: "Log", gruppe: "Indhold", bruges: "Alt, hvad Fangarr har sendt til Sonarr og Radarr – og alle andre beslutninger.",
    saadan: [
      "<b>Tilføjet</b> viser det, der er sendt til sonarr2, radarr og radarr4k. <b>Hentet?</b> viser, om titlen er kommet hjem.",
      "Tryk på en titel for at åbne den i Sonarr eller Radarr.",
      "<b>Alle beslutninger</b> viser også det, Fangarr har sagt nej til, og hvorfor (fx forkert sprog, findes allerede eller fejl).",
      "Brug knapperne øverst til kun at se én slags beslutning. Under dem står tallene for det seneste døgn.",
    ],
    sub: {tilfoejet: "Det, Fangarr har sendt til Sonarr og Radarr. \"Hentet?\" viser, om titlen er kommet hjem.",
          alle: "Alle beslutninger: tilføjet, afvist, findes allerede, venteliste og fejl – med grunden."}},
  wait: {navn: "Venteliste", gruppe: "Indhold", bruges: "Titler, hvor TheTVDB eller TMDb endnu mangler oplysningerne, en regel kræver.",
    saadan: [
      "Fangarr prøver selv igen med jævne mellemrum (sættes under Indstillinger på denne side) og giver op efter et antal dage.",
      "Står der et <b>muligt match</b> (fx dansk titel, men engelsk navn hos TheTVDB), så tryk <b>Godkend</b> ved det rigtige. Det kommer også under Kræver din handling på Overblik.",
      "<b>Prøv nu</b> slår titlen op med det samme. <b>Fjern</b> tager den af listen (den kan komme igen ved næste udgivelse). <b>Fjern og husk</b> holder den væk fremover.",
      "En godkendt kobling huskes, så næste udgivelse med samme titel matches af sig selv (se Godkendte koblinger).",
    ],
    sub: {venter: "Titler, der venter på TheTVDB/TMDb. Godkend et muligt match, eller fjern titlen.",
          koblinger: "Koblinger, du har godkendt (fx \"Simon Siger\" = \"Simon Says (2026)\"). Næste udgivelse med samme titel matches af sig selv.",
          fjernede: "Titler, du har fjernet med \"Fjern og husk\". De kommer ikke på ventelisten igen. Tryk Glem for at give titlen en ny chance.",
          indst: "Hvor tit ventelisten prøver igen, hvornår den giver op, og hvor tit nye serier opdateres i Sonarr."}},
  tr: {navn: "Oversættelser", gruppe: "Indhold", bruges: "Hvad Oversætteren laver, hvad det koster, og hvad der venter på dansk tekst.",
    saadan: [
      "<b>Status</b> viser, hvad Oversætteren laver lige nu, månedens forbrug, statistik og de færdige oversættelser.",
      "<b>Venter</b> viser film og afsnit, der er skjult for kunderne, fordi de mangler dansk tekst – og udgivelser, der holdes tilbage i 6 timer i håb om en NORDiC-udgave.",
      "<b>Problemer</b> er titler, der ikke kunne oversættes. Tryk <b>Prøv igen</b> eller <b>Opgiv</b> (så vises titlen uden dansk tekst efter sikkerhedsnettet). Du får også et tal under Kræver din handling.",
      "<b>Oversæt en titel</b>: søg en serie eller film frem, vælg sæsoner, og se prisen, før du oversætter.",
      "Siden opdateres hvert minut, mens den er åben.",
    ],
    sub: {status: "Hvad Oversætteren laver lige nu, forbruget denne måned, statistik og de færdige oversættelser.",
          venter: "Film og afsnit, der er skjult for kunderne, til de har dansk tekst – og udgivelser, der holdes tilbage af ventetiden.",
          problemer: "Titler, der ikke er blevet oversat. Grunden er Oversætterens egen forklaring.",
          titel: "Søg en serie eller film frem fra Sonarr/Radarr, vælg sæsoner, og se prisen, før du oversætter. \"Ingen ventetid fremover\" sætter mærket straks, så nye afsnit hentes uden de 6 timer.",
          indst: "Kun visning. Oversætterens indstillinger ændres i /opt/oversaetter/.env, ventetiden i Sonarr/Radarr › Settings › Profiles."}},
  bib: {navn: "Bibliotek", gruppe: "Indhold", bruges: "Statistik over det, Fangarr har tilføjet: hvor meget det fylder, og hvor meget det bliver set.",
    saadan: [
      "Tryk <b>Beregn nu</b> for at regne statistikken ud. Det kan tage et par minutter.",
      "Øverst står tallene pr. regel, så du kan se, hvilke regler der giver noget, kunderne ser.",
      "Vælg <b>Ingen har set dem efter 30 dage</b> for at finde kandidater til oprydning.",
      "Tryk på en kolonne for at sortere. Afspilningerne kommer fra Tracearr.",
    ]},
  rules: {navn: "Regler", gruppe: "Indhold", bruges: "Reglerne, der bestemmer, hvad Fangarr tilføjer, og hvor det lægges.",
    saadan: [
      "Reglerne tjekkes oppefra. Den første regel, der passer, bestemmer, hvor titlen lægges. Flyt en regel med pilene.",
      "<b>+ Ny regel</b> laver en ny regel. <b>Slå fra</b> sætter en regel på pause uden at slette den.",
      "<b>Afprøv en titel</b> og <b>Prøv på historikken</b> viser, hvad der ville ske – uden at noget bliver tilføjet.",
      "<b>autobrr</b> laver filtrene i autobrr ud fra reglerne. Bruges kun ved opsætning.",
      "Under <b>Indstillinger</b> slår du prøvetilstand til og fra og sætter dagsloft og pladsgrænse.",
    ],
    sub: {regler: "Reglerne tjekkes oppefra. Den første regel, der passer, bestemmer, hvor titlen lægges.",
          afproev: "Se, hvad der ville ske med en udgivelse – uden at noget bliver tilføjet eller logget.",
          historik: "Kør en regel på de udgivelser, autobrr har set de seneste dage, og se, hvad den ville have fanget. Intet bliver tilføjet. autobrr gemmer kun udgivelser, der har passet et af dine filtre.",
          autobrr: "Fangarr laver filtrene til autobrr ud fra dine regler. Ord som NORDiC og DANiSH hentes fra reglernes \"skal indeholde\".",
          indst: "Prøvetilstand, højst antal nye titler pr. døgn, pladsgrænsen og samspillet med autobrr og Seerr."}},
  cust: {navn: "Kunder", gruppe: "Kunder", bruges: "Alle kunder med tjenester, priser og betalingscyklus – og IPTV-linjer og delte logins.",
    saadan: [
      "Plex-brugere hentes fra Tautulli hver nat og med <b>Synk fra Tautulli</b>. Kunder uden Plex opretter du selv med <b>Ny kunde</b>.",
      "Tryk på en kunde for at åbne kundekortet: tjenester, pris, cyklus, betalingsmetode, fradrag, IPTV-linjer og Seerr-ønsker.",
      "Én kunde kan betale for flere konti og tjenester. Brug <b>Flet ind i anden kunde</b> på kortet, når en anden betaler for kontoen.",
      "<b>IPTV-linjer</b>: alle linjer med udløbsdato. Tryk <b>Fornyet</b>, når du har fornyet en linje hos leverandøren.",
      "Kunder, der mangler cyklus, betalingsmetode eller pris, bliver ikke opkrævet. De står under Kræver din handling.",
    ],
    sub: {iptv: "Alle linjer med udløbsdato. Den 1. i måneden får du besked på Stream365 Drift om, hvor mange der skal fornyes. Brugernavn og kode vises først, når du trykker Vis kode.",
          logins: "Logins til konti, som flere kunder deler (fx Spotify, YouTube). Koden vises først, når du trykker Vis, og den står aldrig i loggen eller i Telegram.",
          indst: "Påmindelser om betaling, frister, pris for en ny Plex-konto og hvornår beskeder og synk kører."}},
  pay: {navn: "Opkrævning", gruppe: "Kunder", bruges: "Månedens opkrævninger: hvem der skal betale, hvem der er anmodet, og hvem der har betalt.",
    saadan: [
      "Månedens liste laves af sig selv ud fra kundernes cyklus. Du får besked i Telegram om morgenen på dagen.",
      "Tryk <b>Send besked</b> for at se beskeden til kunden. Derfra åbner du chatten i Telegram eller Messenger med beskeden klar, og kunden sættes selv til <b>Anmodet</b> – du trykker stadig selv send i appen. Fangarr skriver aldrig selv til kunderne.",
      "Har du anmodet på anden vis, så tryk <b>Anmodet</b>. Tryk <b>Betalt</b>, når pengene er kommet.",
      "Betalingsdatoen er kundens faste dato i måneden (sættes på kundekortet). Kunder uden fast dato regnes som den 1. Tryk <b>I dag</b> for at se dem, der skal opkræves i dag.",
      "<b>Økonomi</b> viser indtægt mod udgifter for hele året. Beskeden og nyheden i opkrævningen retter du under <b>Beskeder</b>.",
      "<b>Udgifter</b>: dine faste udgifter med beløb pr. måned eller år og næste fornyelse. Når varslet nås, kommer \"Forny …\" på huskelisten. Tryk Udført, når den er fornyet – så rykkes datoen frem.",
      "Påmindelsen om manglende betaling i Telegram har knapperne <b>Betalt</b> og <b>+1 uge</b> (ingen påmindelse om kunden i en uge). Efter et tryk kan du fortryde.",
    ],
    sub: {opkraevning: "Månedens opkrævninger. Send besked → Anmodet → Betalt.",
          oekonomi: "Indtægt fra kunderne mod udgiften til IPTV-linjer og dine faste udgifter. Tidligere måneder viser det, der er betalt. Kommende måneder er et skøn ud fra de kunder og priser, du har nu.",
          udgifter: "Dine faste udgifter (Hetzner, domæne, IPTV-leverandør …) med næste fornyelse. Bruges i Økonomi, og fornyelsen kommer på huskelisten."}},
  besk: {navn: "Beskeder", gruppe: "Kunder", bruges: "Teksterne i beskederne til kunderne – samlet ét sted.",
    saadan: [
      "<b>Skabeloner</b>: beskeden, der kommer frem, når du trykker Send besked under Opkrævning. Felterne i {krøllede parenteser} fyldes ud for hver kunde.",
      "<b>Nyhed i opkrævningen</b>: en kort nyhed, der kommer med i opkrævningsbeskeden. Hver kunde får den én gang – med sin næste opkrævning.",
      "Fangarr sender aldrig selv beskeder til kunderne. Du sender dem altid selv fra Telegram eller Messenger.",
      "Husk at trykke Gem, når du har rettet noget.",
    ],
    sub: {skabeloner: "Beskeden til kunden ved opkrævning. Ændringen gælder fra næste gang, du trykker Send besked.",
          nyhed: "Hver kunde får nyheden én gang – med sin næste opkrævning – så den når alle, også dem der betaler hvert kvartal, halvår eller år. Den bliver stående, til du trykker Fjern. Den sættes ind, hvor der står {nyhed} i skabelonen."}},
  oensker: {navn: "Seerr-ønsker", gruppe: "Kunder", bruges: "Hvem der må ønske film og serier i Seerr – pakker, købte ønsker og familie.",
    saadan: [
      "Kunder med en <b>pakke</b> eller <b>købte ønsker</b> kan ønske. <b>Familie</b> (type Egen på kundekortet) kan ønske ubegrænset og gratis. Alle andre kan ikke ønske.",
      "Pakker og enkeltkøb vælger du på kundekortet under Seerr-ønsker. Beløbet lægges selv på kundens næste betaling.",
      "Fangarr gennemgår Seerr hvert 5. minut og lige efter en ændring. <b>Gennemgå Seerr nu</b> gør det med det samme.",
      "<b>Bremsen</b> stopper, hvis for mange ville miste retten på én gang. Admin og konti under <b>Rør ikke</b> røres aldrig.",
      "Under Indstillinger nederst: priser, pakker og Køb i guiden (\"Få flere ønsker\").",
    ]},
  share: {navn: "Kontodeling", gruppe: "Kunder", bruges: "Finder tv, der aldrig har stået hos kunden, og viser den bedste måde at blokere dem på i Tracearr.",
    saadan: [
      "Vælg periode, og tryk <b>Analysér</b>. Allerførste gang hentes hele Tautullis historik – det kan tage et par minutter. Derefter huskes den, også efter en opdatering.",
      "Telefoner, tablets og computere tæller ikke som tv. Ét tv ad gangen på forskellige adresser er tilladt.",
      "Åbn en bruger for at se stederne, beviset og <b>Bedste blokering</b>. Fangarr blokerer ikke selv – du laver reglen i Tracearr.",
      "Har Fangarr valgt forkert sted, så tryk <b>Dette er kundens</b> på det rigtige sted. Dit valg huskes ved alle senere analyser.",
      "<b>Skæringsdato</b> deler perioden i Før og Efter, fx datoen du lavede en regel – så ser du, om den virker.",
      "Intet kører af sig selv endnu, og Fangarr skriver ikke til nogen.",
    ]},
  guide: {navn: "Guide", gruppe: "Kunder", bruges: "Det, der sker på guide.stream365.vip: hvem der har været inde, og nyhederne øverst i guiden.",
    saadan: [
      "<b>Besøg</b>: hvem der har været inde, hvornår, hvilke afsnit de har læst, og hvad de har søgt efter. Navnene kommer fra Kunder. Din egen konto tælles ikke med.",
      "Et besøg er, når en bruger åbner guiden efter mindst 30 minutters pause. Et afsnit tælles, når det har stået midt på skærmen i 5 sekunder.",
      "<b>Søgeord</b> viser, hvad kunderne leder efter – og hvad guiden mangler.",
      "<b>Nyheder</b>: det farvede kort øverst i guiden til tilbud, nyheder og vigtige beskeder. Skriv nyheden, se forhåndsvisningen, og tryk <b>Udgiv</b>.",
      "Der gemmes ingen IP-adresser, og alt ældre end 90 dage slettes af sig selv.",
    ],
    sub: {besoeg: "Hvem der har været inde, hvornår, hvilke afsnit de har læst, og hvad de har søgt efter.",
          nyheder: "Kunderne ser en udgivet nyhed inden for et minut og kun i den periode, du vælger. Knappen på kortet kan åbne en pop-up eller føre til et afsnit i guiden. Er der flere aktive nyheder, kan kunden bladre mellem dem."}},
  drift: {navn: "Drift", gruppe: "System", bruges: "Din huskeliste, om de apps, Fangarr taler med, svarer – og hvad der sker hos trackerne.",
    saadan: [
      "<b>Huskeliste</b>: ting med en dato, fx \"slet den gamle kopi\" eller \"tjek scriptet efter første kørsel\". Skriv hvilken server og evt. en kontrolkommando – den vises med en kopiknap. Opgaver kan gentages (fx hver måned).",
      "På dagen står opgaven under Kræver din handling, og du får én besked i Stream365 Drift med knapperne <b>Udført</b> og <b>Udsæt en dag</b>. Klokkeslættet sættes under Indstillinger › Telegram.",
      "<b>Forbindelser</b> viser, om sonarr2, radarr, autobrr, Seerr, Tautulli, Tracearr, Oversætteren og Plex svarer Fangarr. Kun dem, der er sat op i fangarr.env, vises.",
      "Svarer en app ikke, kommer den under Kræver din handling på Overblik, og der står et tal ved Drift i menuen.",
      "<b>Trackere</b> viser hentegrænsen: afsnit, som trackeren har afvist, og som Fangarr søger igen i små portioner.",
      "Fangarr ændrer intet i apps på denne side – den viser kun.",
    ],
    sub: {huskeliste: "Opgaver med dato. På dagen: under Kræver din handling og en besked med Udført og Udsæt en dag.",
          forbindelser: "Svarer de apps, Fangarr taler med? Tjekkes højst hvert minut.",
          trackere: "Afsnit, som trackeren har afvist (\"API Grab Limit reached\"), og som Fangarr søger igen af sig selv."}},
  settings: {navn: "Indstillinger", gruppe: "System", bruges: "Det, der gælder hele Fangarr: Telegram, eksport og import, apps og widget.",
    saadan: [
      "Indstillinger, der hører til én funktion, ligger hos funktionen som sidste underfane (fx Regler › Indstillinger og Venteliste › Indstillinger).",
      "<b>Telegram</b>: om beskederne til Stream365 Drift er sat op, hvornår det daglige resumé og huskelisten kommer, og om beskederne har knapper.",
      "<b>Knapper i Stream365 Drift</b>: på beskeder, hvor du skal gøre noget (betaling, forslag på ventelisten, nye premierer, huskeliste, 0 streams, vist uden dansk tekst). Fangarr henter selv dine tryk hos Telegram – der er ingen ny adresse udefra. Kun tryk fra din egen chat tages imod. Efter et tryk står det i beskeden, hvad der skete, og der er en Fortryd-knap, hvor det giver mening.",
      "<b>Eksport og import</b>: hent eller gem en fil med regler og indstillinger. Der laves også en eksport hver nat.",
      "<b>Apps og widget</b>: apps på Overblik og i widgetten på telefonen kommer fra Uptime Kuma. Her retter du adresser og tilføjer apps uden lampe.",
      "Husk at trykke Gem, når du har ændret noget.",
    ],
    sub: {telegram: "Alle driftsbeskeder går til Telegram-botten Stream365 Drift – nu med knapper, du kan trykke på.",
          eksport: "Eksporten indeholder regler, indstillinger, autobrr-valg, ventelisten, koblinger og fjernede titler – ingen API-nøgler og ingen kunder.",
          apps: "Apps på Overblik og i widgetten på telefonen."}},
  hjaelp: {navn: "Hjælp", gruppe: "System", bruges: "Alle funktioner i Fangarr forklaret på én side. Søg, eller tryk på en funktion for at åbne den.",
    saadan: [
      "Skriv et ord i søgefeltet, fx <i>betaling</i>, <i>oversæt</i> eller <i>blokering</i>.",
      "Tryk på et navn for at gå direkte til funktionen.",
      "Hold musen over en knap (eller tryk længe på telefonen) for at se, hvad den gør.",
      "Samme tekst står øverst på hver side under \"Sådan bruger du siden\".",
    ]},
};

// Navne på underfanerne (til siden Hjælp) – teksten på knapperne i index.html
const HJ_SUBNAVN = {};

// Forklaring på knapper, som ikke selv har en (title). Nøglen er teksten på knappen.
const KNAP = {
  "Opdatér": "Hent siden igen nu", "Tjek igen": "Spørg apps igen nu", "Gem": "Gem det, du har rettet", "Gem indstillinger": "Gem indstillingerne på denne side",
  "Annullér": "Luk uden at gemme", "Luk": "Luk vinduet",
  "Godkend": "Ja, det er den rigtige titel. Den tilføjes med reglens mappe, profil og mærke, og koblingen huskes.",
  "Prøv nu": "Slå titlen op igen med det samme", "Fjern": "Fjern fra listen nu", "Fjern og husk": "Fjern titlen, og lad den ikke komme på ventelisten igen",
  "Glem": "Giv titlen en ny chance på ventelisten",
  "Tilføj nu": "Læg serien i Sonarr med det samme", "Følg": "Sæt serien på ventelisten, så den tilføjes, når TheTVDB har den",
  "Prøv igen": "Behandl titlen forfra i Oversætterens næste runde", "Opgiv": "Fjern titlen fra listen. Den vises i Plex uden dansk tekst efter sikkerhedsnettet",
  "Oversæt nu": "Oversæt med det samme – se prisen først", "Skjul for kunderne": "Skjul titlen i Plex, til den har dansk tekst", "Tag med igen": "Tag titlen med i oversættelserne igen",
  "Send besked": "Se beskeden til kunden og åbn chatten i Telegram eller Messenger. Kunden sættes til Anmodet", "Anmodet": "Du har bedt kunden betale på anden vis",
  "Betalt": "Pengene er kommet", "Fortryd betalt": "Sæt opkrævningen tilbage til Anmodet", "Opret dem nu": "Opret opkrævningerne for måneden ud fra kundernes cyklus",
  "Ret": "Ret denne linje", "Redigér": "Ret reglen", "Rediger": "Ret", "Slet": "Slet – kan ikke fortrydes", "Slå fra": "Sæt reglen på pause uden at slette den", "Slå til": "Brug reglen igen",
  "↑": "Flyt op", "↓": "Flyt ned", "Kopiér": "Kopiér til udklipsholderen", "Vis": "Vis koden", "Vis kode": "Vis brugernavn og kode", "Sæt ind": "Indsæt fra udklipsholderen",
  "Fornyet": "Linjen er fornyet hos leverandøren – udløbsdatoen rykkes frem", "Tilføj linje": "Tilføj en IPTV-linje til kunden", "Tilføj tjeneste": "Tilføj en tjeneste (fx en Plex-konto) til kunden",
  "Flet ind i anden kunde": "En anden kunde betaler for denne konto – flyt alt over til den kunde", "Køb ønsker": "Køb enkelte film eller sæsoner til kunden",
  "Udgiv": "Vis nyheden i guiden – kunderne ser den inden for et minut", "Gem kladde": "Gem uden at vise den i guiden", "Send igen": "Vis nyheden igen for alle",
  "Åbn pop-up'en": "Se pop-up'en, som kunden vil se den", "Vis import-JSON": "Vis filteret, så du kan importere det i autobrr (Filters › Import)",
  "Opret i autobrr": "Opret filteret i autobrr nu", "Opdatér i autobrr": "Ret filteret i autobrr nu", "Del …": "Del beskeden med en anden app",
  "Analysér": "Find fremmede tv i den valgte periode", "Beregn nu": "Regn statistikken ud igen – kan tage et par minutter", "Beregn igen": "Regn statistikken ud igen",
  "Afprøv": "Se, hvad der ville ske – intet bliver tilføjet", "Prøv reglen": "Kør reglen på historikken – intet bliver tilføjet", "Søg": "Søg i Sonarr og Radarr",
  "Ny kunde": "Opret en kunde uden Plex (Plex-brugere kommer selv fra Tautulli)", "Ny linje": "Opret en IPTV-linje", "Nyt login": "Gem et login, som flere kunder deler",
  "+ Ny regel": "Lav en ny regel", "Ny nyhed": "Skriv en ny nyhed til guiden", "Denne måned": "Gå til denne måned",
  "Dette er kundens": "Dette sted er kundens hjem – gemmes og gælder ved alle senere analyser", "Ikke kundens": "Dette sted er ikke kundens",
  "Godkend undtagelse": "Sommerhus eller lignende, som kunden har lov til", "Fjern valg": "Slet din afgørelse for stedet",
  "Udført": "Opgaven er gjort. Gentages den, rykkes den til næste dato", "Udsæt en dag": "Flyt opgaven til i morgen", "Fortryd udført": "Sæt opgaven på huskelisten igen",
  "Ny opgave": "Læg en ny opgave på huskelisten", "Vis udførte": "Se de opgaver, du har markeret udført", "Vis det, der mangler": "Tilbage til opgaverne, der mangler",
  "Ny udgift": "Tilføj en fast udgift med beløb og fornyelse", "Sig til ved 0 streams": "Få én besked i Stream365 Drift, når ingen streamer",
  "Stop": "Du får ingen besked alligevel", "Ikke interesseret": "Vis ikke premieren igen under Kræver din handling",
  "Hent historikken forfra": "Glem den huskede historik og hent alt fra Tautulli igen", "Gennemgå Seerr nu": "Gennemgå Seerr nu i stedet for om højst 5 minutter",
};

// ---------- beskrivelserne øverst på siderne og underfanerne
function fillDescriptions() {
  document.querySelectorAll(".subs button").forEach(b => {
    const sec = b.closest("section").id; HJ_SUBNAVN[sec + "/" + b.dataset.sub] = b.firstChild.textContent.trim(); });
  document.querySelectorAll("[data-hj]").forEach(el => {
    const h = HJ[el.dataset.hj]; if (!h) return;
    el.innerHTML = `<h2 class="pt">${esc(h.navn)}</h2><p class="hint bruges"><b>Bruges til:</b> ${esc(h.bruges)}</p>` +
      `<details class="hjd"><summary>Sådan bruger du siden</summary><ul>${h.saadan.map(x => `<li>${x}</li>`).join("")}</ul></details>`;
  });
  document.querySelectorAll("[data-hjs]").forEach(el => {
    const [p, s] = el.dataset.hjs.split("/"), t = ((HJ[p] || {}).sub || {})[s];
    if (t) el.textContent = t; else el.remove();
  });
  tipAll(document);
}

// ---------- siden Hjælp: alle funktioner på én side, med søgefelt
function renderHelp() {
  const q = ($("hjq").value || "").trim().toLowerCase();
  const strip = t => String(t).replace(/<[^>]+>/g, "");
  const order = ["home", "log", "wait", "tr", "bib", "rules", "cust", "pay", "besk", "oensker", "share", "guide", "drift", "settings"];
  let grp = null, out = "";
  for (const id of order) {
    const h = HJ[id], subs = Object.entries(h.sub || {});
    const all = [h.navn, h.bruges, ...h.saadan, ...subs.flat(), ...subs.map(([s]) => HJ_SUBNAVN[id + "/" + s] || "")].map(strip).join(" ").toLowerCase();
    if (q && !q.split(/\s+/).every(w => all.includes(w))) continue;
    if (h.gruppe !== grp) { grp = h.gruppe; out += grp ? `<h3 class="hjg">${esc(grp)}</h3>` : ""; }
    out += `<div class="card hjc"><div class="row" style="justify-content:space-between;margin:0"><h2 style="margin:0"><a href="#${id}" onclick="go('${id}');return false">${esc(h.navn)}</a></h2></div>
      <p class="hint" style="margin:4px 0 8px"><b>Bruges til:</b> ${esc(h.bruges)}</p><ul class="hjl">${h.saadan.map(x => `<li>${x}</li>`).join("")}</ul>` +
      (subs.length ? `<div class="hjsubs">${subs.map(([s, t]) => `<div><a href="#${id}/${s}" onclick="go('${id}','${s}');return false"><b>${esc(HJ_SUBNAVN[id + "/" + s] || s)}</b></a> – ${esc(t)}</div>`).join("")}</div>` : "") + "</div>";
  }
  $("hjOut").innerHTML = out || `<div class="card empty">Intet i hjælpen om “${esc(q)}”.</div>`;
}

// ---------- forklaring på knapper: musen over (title) og langt tryk på telefonen
function tipAll(root) {
  root.querySelectorAll("button, a.b").forEach(b => {
    if (b.title || b.dataset.tip === "0") return;
    const t = KNAP[b.textContent.trim()];
    if (t) b.title = t;
  });
}
new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => { if (n.nodeType === 1) tipAll(n.parentNode || n); })))
  .observe(document.body, {childList: true, subtree: true});
let tipTimer = null;
document.addEventListener("touchstart", e => {
  const b = e.target.closest("button[title], a.b[title], a.app[title]"); if (!b) return;
  tipTimer = setTimeout(() => { toast(b.title); b.dataset.longpress = "1"; }, 550);
}, {passive: true});
["touchend", "touchmove", "touchcancel"].forEach(ev => document.addEventListener(ev, () => clearTimeout(tipTimer), {passive: true}));
// et langt tryk viser kun forklaringen – det trykker ikke på knappen
document.addEventListener("click", e => { const b = e.target.closest("[data-longpress]"); if (b) { delete b.dataset.longpress; e.preventDefault(); e.stopImmediatePropagation(); } }, true);
