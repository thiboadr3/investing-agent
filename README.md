# Investing Agent (paper trading)

AI-gedreven agent die een **paper**-portefeuille bij Alpaca beheert. Geen echt geld.

## Hoe het werkt

1. **Data** — dagkoersen (Alpaca IEX, gratis) en nieuws (Alpaca News) voor een vaste lijst van 30 symbolen in `config.yaml`.
2. **AI (Gemini)** — krijgt koersstatistieken, huidige gewichten en nieuws, en stelt per symbool *buy / sell / hold* + doelgewicht + zekerheid + argumenten voor. Nieuws wordt als onbetrouwbare tekst behandeld.
3. **Strategie** — zet doelgewichten om in ordervoorstellen (eerst verkopen, dan kopen).
4. **Risicolaag** (`agent/risk.py`, zonder AI) — weigert elke order die een regel schendt:
   - noodstop actief, accountstatus onduidelijk, markt dicht
   - symbool niet in de lijst, al een open order, >10 orders per dag
   - order < $100, AI-zekerheid < 0,6, koersdata te oud
   - **kopen** geblokkeerd bij ≥ 15 % terugval vanaf de piek, positie > 10 %, cash < 5 %
   - **verkopen** enkel van wat je bezit (geen shorts)
5. **Broker** — plaatst uitsluitend paperorders (weigert te starten op een live-endpoint), met vaste order-ID's per dag zodat een herstart nooit dubbele orders geeft.
6. **Logboek** — alles in `data/agent.db` (SQLite): beslissingen + argumenten, orders, weigeringen, nieuws, snapshots, fouten.

Schema in `run`-modus: tijdens beursuren elke 15 min posities/orders controleren, één AI-analyse per beursdag ~20 min na de opening; buiten beursuren elk uur nieuws bewaren.

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
python -m agent once --dry-run                          # testrun tijdens beursuren
python -m agent once                                    # één echte paper-cyclus
python -m agent run                                     # doorlopend (server)
```

**Noodstop:** maak een leeg bestand `STOP` in deze map (`touch STOP`). Verwijder het om te hervatten.

Logboek bekijken: `sqlite3 data/agent.db "select * from decisions order by ts desc limit 20"`.

## In de cloud: GitHub Actions

`.github/workflows/agent.yml` start de agent elke 30 min op weekdagen (13:00–21:30 UTC) met `python -m agent tick`. De agent controleert zelf of de beurs open is, doet één AI-analyse per beursdag en volgt verder enkel op. Het logboek (`agent.db`) wordt na elke run bewaard op de branch `state`.

Instellen (Settings → Secrets and variables → Actions):

| Soort | Naam | Waarde |
|---|---|---|
| Secret | `ALPACA_API_KEY` | Alpaca paper Key ID |
| Secret | `ALPACA_SECRET_KEY` | Alpaca paper Secret |
| Secret | `GEMINI_API_KEY` | Google AI Studio-key |
| Variable | `TRADING_MODE` | `dry_run` (standaard, niets plaatsen) of `paper` |
| Variable | `AGENT_STOP` | `true` = noodstop, geen runs |

Handmatig starten: tab **Actions → Investing Agent → Run workflow** (`status`, `tick` of `once`).

## Nog te doen
- Historische test (backtest) en wekelijkse rapportage t.o.v. SPY
- Meldingen (bv. Telegram of e-mail)
- Belgische kosten/taks en valuta-effect in de evaluatie
