# Investing Agent (paper trading)

AI-gedreven agent die een **paper**-portefeuille bij Alpaca beheert. Geen echt geld.

## Hoe het werkt

0. **Dagritme** — tot 3 uur vóór de opening: onderzoek (data, regels, AI-filter) → kooplijst (plan). Vanaf 5 min na de opening: plan uitvoeren. Daarna enkel opvolging.
1. **Data** — elke ochtend een scan van álle Amerikaanse aandelen (NYSE/NASDAQ/AMEX, ook kleinere bedrijven; geen ETF's/fondsen/warrants), gefilterd op prijs ≥ $5 en ≥ $10 mln dagvolume (Alpaca SIP, gecorrigeerd voor splitsingen/dividenden) en nieuws (Alpaca News). Crypto staat voorlopig **uit** (`crypto.symbols: []`).
2. **Regels** (`agent/rules.py`, zonder AI) bepalen de doelportefeuille:
   - *Aandelen*: enkel boven het 200-daagse gemiddelde én met positief 6-1-maandsmomentum, volatiliteit ≤ 150 %; de sterkste 5; gewicht omgekeerd evenredig met volatiliteit, max 20 % per positie. SPY is enkel de maatstaf.
   - *Crypto*: per munt enkel bij trend (boven 200d-gemiddelde en positief 3m-rendement). Beide munten in trend → 20 %, één → 10 %, geen → 0 %. Max 12 % per munt.
   - Samen 95 % belegd, 5 % cash.
3. **AI-filter (Gemini) met debat** — per positie eerst een argument vóór en tegen, dan pas de beslissing; mag enkel **halveren of schrappen** bij een concrete rode vlag (nooit vergroten). Levert ook de bedrijfsfiche. Krijgt de **lessen** uit eerdere weekevaluaties als context. Faalt de AI, dan worden er die dag enkel verkopen gedaan.
4. **Risicolaag** (`agent/risk.py`) weigert elke order die een regel schendt: noodstop, accountstatus, beurs dicht (aandelen), symbool niet toegelaten, open order, max orders/dag, te kleine order, verouderde data, ≥ 15 % terugval (geen aankopen), positie- en crypto-limieten, cashbuffer, geen shorts.
5. **Broker** — enkel paperorders, vaste order-ID's (geen dubbele orders na herstart); crypto met GTC-orders.
6. **Buiten beursuren** (elke 4 uur, ook weekend): crypto-uitstapcontrole — verkoopt een munt als de trend breekt, koopt nooit.
7. **Schaduwportefeuilles** (virtueel, niet verhandeld) om te vergelijken: *regels zonder AI-filter*, *50 % crypto / 50 % aandelen*, *AI volledig vrij*, *SPY kopen en houden*. Met geschatte kosten (aandelen 0,05 %, crypto 0,25 % per transactie).
8. **Rapport** — na elke run in de GitHub Actions-samenvatting en via `python -m agent report`.
9. **Portefeuilleoverzicht** — per positie: wat het bedrijf doet, waarom gekozen (cijfers + AI-fiche), risico, resultaat sinds aankoop, recent nieuws en links. Na elke run bijgewerkt op de branch `state`: [PORTFOLIO.md](https://github.com/thiboadr3/investing-agent/blob/state/PORTFOLIO.md). Lokaal: `python -m agent overview`.
10. **Geheugen** — tradedagboek (elke afgesloten trade: instap- en uitstapreden, resultaat, SPY zelfde periode) en elke vrijdag na sluiting een **weekevaluatie** met lessen en te backtesten hypotheses: [WEEKLY.md](https://github.com/thiboadr3/investing-agent/blob/state/WEEKLY.md). Regels veranderen nooit automatisch.
11. **Backtest** — `python tools/backtest.py fetch` en `run`: zelfde regels op 10 jaar data, varianten, rapport in `research/backtest_report.md`.
12. **Logboek** — alles in SQLite (`agent.db`): beslissingen + redenen, AI-aanpassingen, orders, weigeringen, nieuws, snapshots, schaduwwaarden, kosten.

## Installatie (lokaal, Mac)

```bash
cd "Investing Agent"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # vul je paper-keys in
python -m pytest -q       # risicoregels testen
```

## Gebruik

```bash
python -m agent status                                  # rekening en posities
python -m agent once --dry-run --ignore-market-hours    # veilige testrun, plaatst niets
python -m agent report                                  # echte vs schaduwportefeuilles
python -m agent once --dry-run                          # testrun tijdens beursuren
python -m agent once                                    # één echte paper-cyclus
python -m agent run                                     # doorlopend (server)
```

**Noodstop:** maak een leeg bestand `STOP` in deze map (`touch STOP`). Verwijder het om te hervatten.

Logboek bekijken: `sqlite3 data/agent.db "select * from decisions order by ts desc limit 20"`.

## In de cloud: GitHub Actions

`.github/workflows/agent.yml` start de agent elke 30 min op weekdagen (10:00–21:30 UTC: onderzoek vóór de opening, uitvoering erna, opvolging) met `python -m agent tick`. De agent controleert zelf of de beurs open is, doet één AI-analyse per beursdag en volgt verder enkel op. Het logboek (`agent.db`) wordt na elke run bewaard op de branch `state`.

Instellen (Settings → Secrets and variables → Actions):

| Soort | Naam | Waarde |
|---|---|---|
| Secret | `ALPACA_API_KEY` | Alpaca paper Key ID |
| Secret | `ALPACA_SECRET_KEY` | Alpaca paper Secret |
| Secret | `GEMINI_API_KEY` | Google AI Studio-key |
| Variable | `TRADING_MODE` | niet ingesteld = `paper` (standaard, paperorders) · `dry_run` = enkel loggen |
| Variable | `AGENT_STOP` | `true` = noodstop, geen runs |

Handmatig starten: tab **Actions → Investing Agent → Run workflow** (`status`, `tick` of `once`).

## Nog te doen
- Historische test (backtest) en wekelijkse rapportage t.o.v. SPY
- Meldingen (bv. Telegram of e-mail)
- Belgische kosten/taks en valuta-effect in de evaluatie
