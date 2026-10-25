# Investing Agent — projectcontext

Bijgewerkt: 22 oktober 2026.

## Doel van de gebruiker

Een investing agent bouwen die een portefeuille zelfstandig opvolgt en buys en sells uitvoert op basis van marktanalyses, bedrijfsrapporten, nieuws en andere relevante informatie. Als voorbeeld is een account van €10.000 genoemd, met als doel het kapitaal te laten groeien.

De agent moet in de cloud werken, ook wanneer de pc van de gebruiker uitstaat. Gebeurtenissen in andere tijdzones moeten kunnen worden verwerkt. Continu analyseren betekent niet dat alle instrumenten continu verhandelbaar zijn.

De gebruiker wil eerst volledig gratis testen met paper trading. Er is nog geen toestemming gegeven om echt geld te verhandelen.

## Huidige status

- Gebruiker start volledig vanaf nul: nog geen Alpaca-, Google AI Studio- of Oracle Cloud-account (22 okt 2026).
- Codeskelet gebouwd (Python): config, paper-only Alpaca-adapter, koersdata + Alpaca News, Gemini-analyse, onafhankelijke risicolaag, SQLite-logboek, scheduler, noodstop en tests. Zie README.md.
- Test 22 okt 2026 19:29 op de Mac (via 'Test agent.command', Python 3.9.6): 7 tests OK; Alpaca paper OK (ACTIVE, $10.000); koersdata en nieuws OK (50 berichten).
- 22 okt 2026 19:45: netwerkdomeinen toegestaan; Claude test nu zelf via device_bash (Linux-venv in $HOME/venv-ia, `IA_DB_PATH=$HOME/ia-data/agent.db` omdat SQLite niet kan schrijven in de gekoppelde map).
- Eerste volledige dry-run geslaagd: model gemini-3.8-flash, 10 AI-voorstellen, 7 orderkandidaten (XOM, LLY, BRK.B, V, PG, XLV, COST; elk 7-8%), niets geplaatst.
- Gemini: automatische nieuwe pogingen bij 503/429 + reservemodellen (config.yaml > ai.fallback_models). 'gemini-2.5-flash' niet meer beschikbaar voor nieuwe gebruikers.
- requirements werken op Python 3.9 (Mac) en 3.10+. .env door gebruiker ingevuld (keys nooit tonen; Claude kan .env niet schrijven).
- Oracle lukte niet bij de gebruiker → gekozen: GitHub Actions. Workflow `.github/workflows/agent.yml` (elke 30 min op weekdagen 13–21 UTC, `python -m agent tick`), logboek op branch 'state', standaard dry-run; repo-variabele TRADING_MODE=paper voor paperorders, AGENT_STOP=true als noodstop. Keys als GitHub Secrets (gebruiker voert zelf in).
- 22 okt 2026 20:25: GitHub-repo thiboadr3/investing-agent (private) is nu de HOOFDVERSIE van de code. Secrets ingesteld; 2 handmatige 'status'-runs geslaagd (Alpaca OK, logboek blijft bewaard op branch 'state'). Planning actief, standaard dry-run (variabele TRADING_MODE niet gezet). Het lokale .github/workflows/agent.yml is verouderd; Claude mag het daar niet schrijven.
- Open: Gemini-project 'Investment Agent' staat nog op Free tier → gebruiker moet in AI Studio 'Set up billing' doen. Kostenrem: max 12 AI-aanroepen/dag; kosten geschat en gelogd.
- Gemini gratis tier: vaak 503 (overbelast) en 429 (quota). Agent faalt dan veilig (geen orders) en probeert bij volgende run opnieuw. Time-out 75 s per aanroep; modelvolgorde 3.8-flash → 3.5-flash → 3.7-flash → flash-latest.
- Vraag crypto vs aandelen besproken: voorlopig aandelen/ETF's; crypto eventueel later als apart klein deel met eigen risicoregels.
- (Oud) Volgende stap: Oracle Cloud Free Tier-account (gebruiker) en server inrichten via Cloud Shell in de browser; daarna `python -m agent run` als systemd-service.
- Nog geen server ingericht.
- Broker, cloudprovider, AI-model en strategie zijn voorstellen, nog geen definitieve keuzes.
- Dit bestand bewaart de gesprekscontext; het is geen bewijs van winstgevendheid of definitief beleggingsadvies.

## Voorgestelde gratis testsetup

| Onderdeel | Voorstel | Aandachtspunt |
|---|---|---|
| Paperbroker | Alpaca Paper Only | Volgens documentatie gratis en wereldwijd aan te maken met e-mailadres; geen storting nodig. Live-accounttoegang staat hiervan los. |
| Marktdata | Alpaca Basic | Gratis Amerikaanse aandelen- en ETF-data; realtime IEX-feed dekt niet de volledige markt. Quota en rechten controleren bij implementatie. |
| AI-analyse | Een model binnen de gratis Gemini API-tier | Model- en accountafhankelijke quota; bij uitputting nieuwe AI-afhankelijke beslissingen overslaan. Actuele beschikbaarheid en datavoorwaarden controleren. |
| Cloudserver | Oracle Cloud Always Free | Binnen gratis resources; beschikbaarheid/capaciteit niet gegarandeerd. Als inactief aangemerkte instances kunnen worden teruggenomen. Kaartverificatie kan nodig zijn. |
| Applicatie en opslag | Python + SQLite | Op server, met persistente opslag, automatische herstart en herstel na storingen. |
| Rapportage | Alpaca-dashboard en eigen beslissingslog | Later eventueel eigen dashboard en meldingen; meldingskanaal nog niet gekozen. |
| Rapporten en nieuws | SEC EDGAR, bedrijfsberichten en toegestane openbare feeds | Geen volledige professionele nieuwsdekking. Gebruiksrechten, actualiteit en bronkwaliteit controleren. |

Een test van €0 is mogelijk binnen de gratis quota, maar is geen garantie op blijvend gratis of ononderbroken functioneren. Geen betaalde upgrades of diensten activeren zonder afstemming.

Alpaca-paperportefeuille zou bijvoorbeeld met **$10.000** starten. Dit is geen exacte simulatie van de genoemde **€10.000**: eurobenchmark en valuta-effecten moeten apart worden verwerkt als we het oorspronkelijke doel exact willen volgen.

Interactive Brokers is eerder onderzocht als mogelijke latere broker: API voor orders, rekeninggegevens en posities, plus paper trading. Veel API-marktdata vereist abonnementen. Handelsrechten, accountvoorwaarden en authenticatie moeten voor de concrete account worden geverifieerd.

## Voorgestelde werking

1. Marktdata, nieuws en rapporten ophalen, met bron en publicatietijd.
2. AI formuleert een analyse en argumenten voor en tegen een positie.
3. Expliciete strategieregels bepalen kopen, verkopen of niets doen.
4. Een onafhankelijke risicolaag valideert elke order.
5. De brokeradapter plaatst uitsluitend paperorders en controleert de werkelijke orderstatus en posities.
6. Alle beslissingen, brongegevens, fouten en resultaten worden opgeslagen.

Voorlopige planning als voorbeeld:

- Elk uur relevante nieuwsbronnen controleren, ook buiten beursuren.
- Uitgebreide analyse vóór de relevante beursopening.
- Tijdens handelsuren iedere 15 minuten posities en orders controleren.
- Beurskalenders, tijdzones en zomer-/wintertijd correct verwerken.

Dit schema is nog niet definitief. Geen vereiste voor high-frequency trading of iedere minuut een volledige AI-analyse.

## Gekozen uitgangspunten (22 okt 2026)

- Strategie (v1, vervangen door v2 hieronder): vooral AI-gedreven.
- Maximale terugval: -15% vanaf piek → geen nieuwe aankopen (verkopen blijft mogelijk).
- Maximale positie: 10% van de portefeuille. Cashbuffer 5%, min. AI-zekerheid 0,6, max. 10 orders per dag.
- Benchmark: S&P 500 (SPY).

## Strategie v2 (22 okt 2026, op voorstel van Claude, akkoord gebruiker)

- Gebruiker vroeg naar crypto vs aandelen; gekozen: aandelen/ETF-basis + crypto 0–20% via trendregels. AI niet meer leidend maar filter (enkel halveren/schrappen bij concrete rode vlag). Faalt AI → enkel verkopen.
- Crypto via Alpaca paper (crypto_status ACTIVE, 36 paren); gekozen munten: BTC/USD, ETH/USD. Max 12% per munt, 20% samen.
- Schaduwportefeuilles (virtueel): regels zonder AI, 50/50, AI vrij (max 25%/positie), SPY. Doel: na x tijd herevalueren welke aanpak het best werkt (rendement + max terugval, na geschatte kosten).
- Crypto-uitstapcontrole elke 4 uur buiten beursuren (enkel verkopen).
- Eerste live dry-run v2 (22 okt 20:45): 12 doelposities (10 aandelen/ETF + BTC/ETH = 20%), 95% belegd; schaduwen werken; 'AI vrij' faalde door gratis quotum.

## Aanpassing 23 okt 2026 (vraag gebruiker)

- Crypto UIT (config `crypto.symbols: []`): eerst volledig focussen op aandelen/ETF's om sneller lessen te trekken. Schaduw 50/50 vervalt zolang crypto uit staat.
- Onderzoek vóór de opening: tot 3 u vóór de opening wordt het plan gemaakt (regels + AI-filter + beslissing 'AI vrij'); uitvoering vanaf 5 min na de opening. Faalde de AI vóór de opening → één nieuwe poging bij de opening. Planning: elke 30 min op weekdagen 10:00–21:30 UTC.
- 23 okt: gebruiker: paper = testfase, paperorders mogen. Workflow staat standaard op PAPER (TRADING_MODE=dry_run om enkel te loggen).
- Repo thiboadr3/investing-agent is nu PUBLIEK (keuze gebruiker). Geplande runs bleken ook privé te werken, met 1–2 u vertraging.
- Fix: koersen nu gecorrigeerd voor splitsingen/dividenden (Adjustment.ALL).
- Live dry-run 23 okt (AI OK, ~$0,02/dag): 10 posities à ~10% (XLE, KO, QQQ, XOM, JNJ, CVX, AAPL, XLK, LLY, NVDA). Aandachtspunt: ~30% energie (XLE+XOM+CVX) → sectorlimiet overwegen.
- Onderzoek 13F (research/): ARK, Situational Awareness, Altimeter, Coatue, Tiger Global. Kopieertest 2026: enkel ARK (+23 pp) en SA (+3 pp) versloegen SPY. Les: thema AI-infra (geheugen/chips) juist; drukke nieuwe AI-namen (CBRS, CRWV) crashten; universum mist winnaars (MU, SNDK, LRCX, AMAT).

## Startstrategie en risicobeheer

Voorstel: een klein universum van circa 10–20 liquide Amerikaanse aandelen/ETF's, zonder hefboom, shortposities of derivaten. Posities kunnen dagen tot maanden blijven staan. Concrete instrumenten en signalen zijn nog niet gekozen.

Nodig vóór implementatie:

- Beleggingshorizon, benchmark en aanvaardbare maximale terugval vastleggen.
- Positie- en concentratielimieten, cashregels en verlieslimieten bepalen.
- AI mag risicoregels niet wijzigen of omzeilen.
- Bescherming tegen dubbele orders en herhaalde uitvoering na een herstart.
- Verouderde of ontbrekende data en onduidelijke rekeningstatus blokkeren nieuwe orders.
- Lokale administratie met brokerposities en uitgevoerde orders vergelijken.
- Noodstop, foutregistratie en herstelprocedure voorzien.
- Nieuws/rapporten als onbetrouwbare invoer behandelen; inhoud mag geen systeeminstructies geven.
- Alleen paper-API-sleutels gebruiken, buiten broncode en chat bewaren. Geen live-credentials nodig voor deze fase.

## Evaluatieplan

1. Historische tests met uitsluitend informatie die toen beschikbaar was; voorkom vooruitkijken en selectiebias.
2. Test op ongeziene periodes en vergelijk met een passende passieve benchmark.
3. Start met ongeveer 8–12 weken cloud-papertrading om werking en beslissingen te beoordelen.
4. Beoordeel rendement, maximale terugval, concentratie, kosten en operationele fouten.

8–12 weken of enkele winstgevende maanden bewijzen geen duurzaam voordeel. Paperuitvoering wijkt af van livehandel. Alpaca vermeldt onder meer ontbrekende simulatie van dividenden, marktimpact en bepaalde slippage-effecten; deze beperkingen moeten in de evaluatie worden verwerkt. Bereken naast het brokerresultaat waar mogelijk een resultaat na geschatte transactiekosten, spreads, valuta en toepasselijke belastingen, zonder kosten dubbel te tellen.

Als de gebruiker fiscaal inwoner van België is, moeten onder andere de taks op beursverrichtingen en de verplichtingen bij een buitenlandse broker worden onderzocht vóór livegebruik. Fiscale woonplaats is nog niet bevestigd.

Eventuele overgang naar echt geld is een afzonderlijke, later expliciet te beslissen fase.

## Openstaande keuzes en volgende stappen

1. Gratis teststack definitief kiezen en actuele quota, voorwaarden en beschikbaarheid controleren.
2. Vaststellen of de gebruiker al Alpaca-, Oracle Cloud- en Google AI Studio-accounts heeft.
3. Strategie, instrumenten, benchmark, valuta en risicolimieten specificeren.
4. Paperagent implementeren, inclusief logging, brokerreconciliatie en veilige pauzestand.
5. Cloudomgeving inrichten en controleren dat de agent werkt terwijl de pc uitstaat.
6. Evaluatieperiode starten en resultaten periodiek beoordelen.

## Bronnen uit het onderzoek

Deze bronnen zijn geraadpleegd tijdens het gesprek op 22 oktober 2026. Controleer veranderlijke voorwaarden opnieuw bij implementatie.

- Alpaca paper trading: https://docs.alpaca.markets/us/docs/paper-trading
- Alpaca marktdata en gratis plan: https://docs.alpaca.markets/us/docs/about-market-data-api
- Gemini API-prijzen en gratis tier: https://ai.google.dev/gemini-api/docs/pricing
- Oracle Always Free en reclamation: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- IBKR API en paperbeperkingen: https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/tws-api-limitations
- IBKR marktdata-abonnementen: https://www.interactivebrokers.com/docs/general/market-data-subscriptions/introduction
- SEC EDGAR: https://www.sec.gov/search-filings
- ESMA over AI bij beleggen: https://www.esma.europa.eu/document/warning-use-ai-investing
- Belgische taks op beursverrichtingen: https://financien.belgium.be/nl/particulieren/internationaal/buitenlandse-inkomsten-en-rekeningen/taks-op-beursverrichtingen

## Werkinstructies uit dit gesprek

Voor browserwerk gelden de door de gebruiker aangeleverde AGENTS.md-instructies: connectors/API's hebben voorkeur; anders uitsluitend eigen, exact geïdentificeerde tabs met tabgebonden bediening. Geen gebruik van actieve gebruikerstabs of globale desktopbediening. Controleer vóór wijzigingen de actuele URL, account-/tenantidentiteit en het bedoelde object. Deze afspraken bieden geen technische sessie-isolatie.

- 25 okt: universum = alle liquide US-aandelen (scan, ook small/mid caps, geen ETF's); rangschikking mom6 (6-1), top 5, max 20%/positie, buffer 5, band 3%, vol-plafond 150%. Grid-backtest S&P 500: mom6 top5 deel1 +8,7%/j (SPY +11,1%), deel2 +43,1%/j (SPY +21,7%), max. daling ~−39%. Small caps zijn NIET eerlijk te backtesten (geen historische lijst) → paper-resultaten zijn de echte toets. Telegram werkt (chat met @albert_investing_bot).
- 25 okt (avond): op vraag van gebruiker beslist de AI nu zelf (optie 1): kiest uit shortlist van 25 (regels: trend + mom6) + huidige aandelen; 3–10 posities; harde risicolimieten blijven. Sectorlimiet expliciet NIET gewenst. Schaduw 'regels zonder AI' meet of de AI waarde toevoegt.
