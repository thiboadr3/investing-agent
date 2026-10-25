# Eerlijke backtest: S&P 500 zonder overlevingsbias

_Gegenereerd 2026-10-25. Elke dag enkel aandelen die toen in de S&P 500 zaten. Zelfde regels als de agent; uitvoering op opening volgende dag; kosten 0,05% per transactie; start $10.000; pauzeregel −15% met reset._

Koersdekking: 714 van 719 tickers die sinds 2017 in de index zaten (99%). Ontbrekende tickers (meestal verdwenen of hernoemd) kunnen niet gekozen worden.

## Volledig 2017–2026

| Variant | Totaal | Per jaar | Max. daling | Sharpe | Kosten | Omzet/jaar |
|---|---:|---:|---:|---:|---:|---:|
| Top 10, max 10% + buffer + band 3% | +259% | +14.0% | −36% | 0.59 | $609 | 12.5× |
| Top 10 + sectorlimiet 25% | +175% | +10.9% | −42% | 0.55 | $1,092 | 22.3× |
| Top 10 + sectorlimiet + marktfilter | +186% | +11.3% | −27% | 0.61 | $1,250 | 25.6× |
| Top 5, max 20% + buffer + band 3% | +329% | +16.1% | −43% | 0.60 | $695 | 14.2× |
| Top 5, max 20% + sectorlimiet 40% | +352% | +16.7% | −43% | 0.65 | $1,205 | 24.6× |
| Top 5 + sectorlimiet + marktfilter | +239% | +13.3% | −35% | 0.59 | $1,158 | 23.7× |
| Top 20, max 5% + buffer + band 2% | +221% | +12.6% | −31% | 0.59 | $508 | 10.4× |
| **SPY kopen en houden** | +293% | +15.0% | −34% | 0.88 | $0 | — |

## Deel 1 (2017–2022)

| Variant | Totaal | Per jaar | Max. daling | Sharpe | Kosten | Omzet/jaar |
|---|---:|---:|---:|---:|---:|---:|
| Top 10, max 10% + buffer + band 3% | +31% | +4.6% | −36% | 0.30 | $362 | 12.1× |
| Top 10 + sectorlimiet 25% | +8% | +1.4% | −42% | 0.18 | $502 | 16.8× |
| Top 10 + sectorlimiet + marktfilter | +40% | +5.8% | −27% | 0.38 | $561 | 18.7× |
| Top 5, max 20% + buffer + band 3% | +15% | +2.4% | −43% | 0.23 | $397 | 13.3× |
| Top 5, max 20% + sectorlimiet 40% | +36% | +5.3% | −43% | 0.32 | $508 | 17.0× |
| Top 5 + sectorlimiet + marktfilter | +46% | +6.6% | −35% | 0.38 | $554 | 18.5× |
| Top 20, max 5% + buffer + band 2% | +11% | +1.8% | −31% | 0.19 | $285 | 9.5× |
| **SPY kopen en houden** | +88% | +11.1% | −34% | 0.64 | $0 | — |

## Deel 2, ongezien (2023–2026)

| Variant | Totaal | Per jaar | Max. daling | Sharpe | Kosten | Omzet/jaar |
|---|---:|---:|---:|---:|---:|---:|
| Top 10, max 10% + buffer + band 3% | +188% | +32.2% | −33% | 0.98 | $204 | 10.8× |
| Top 10 + sectorlimiet 25% | +172% | +30.2% | −25% | 1.17 | $586 | 30.9× |
| Top 10 + sectorlimiet + marktfilter | +119% | +23.0% | −21% | 0.99 | $529 | 27.9× |
| Top 5, max 20% + buffer + band 3% | +302% | +44.3% | −36% | 1.09 | $272 | 14.4× |
| Top 5, max 20% + sectorlimiet 40% | +246% | +38.8% | −33% | 1.12 | $532 | 28.1× |
| Top 5 + sectorlimiet + marktfilter | +141% | +26.1% | −28% | 0.88 | $432 | 22.8× |
| Top 20, max 5% + buffer + band 2% | +200% | +33.7% | −31% | 1.12 | $213 | 11.2× |
| **SPY kopen en houden** | +110% | +21.7% | −19% | 1.40 | $0 | — |

## Rendement per jaar (volledige periode)

| Variant | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Top 10, max 10% + buffer + band 3% | +15% | -25% | +22% | +25% | -4% | +4% | +13% | +30% | +20% | +55% |
| Top 10 + sectorlimiet 25% | +18% | -24% | +15% | +18% | +3% | -12% | +6% | +45% | +29% | +29% |
| Top 10 + sectorlimiet + marktfilter | +18% | -11% | +10% | +20% | +3% | -1% | -2% | +43% | +19% | +21% |
| Top 5, max 20% + buffer + band 3% | +13% | -29% | +30% | +10% | +1% | +1% | +28% | +25% | +23% | +88% |
| Top 5, max 20% + sectorlimiet 40% | +19% | -29% | +32% | +5% | +7% | +10% | +31% | +24% | +32% | +54% |
| Top 5 + sectorlimiet + marktfilter | +19% | -19% | +26% | +7% | +7% | +7% | +8% | +23% | +21% | +44% |
| Top 20, max 5% + buffer + band 2% | +6% | -12% | +11% | +11% | +2% | -5% | +9% | +44% | +20% | +53% |
| **SPY kopen en houden** | +21% | -5% | +31% | +18% | +29% | -18% | +26% | +25% | +18% | +13% |

## Extra: kern + satelliet en SPY met trendfilter

| Variant | 2017–2026 per jaar | Max. daling | Sharpe | 2017–2022 | 2023–2026 |
|---|---:|---:|---:|---:|---:|
| 70% SPY + 30% momentum top 5 | +16,4% | −30% | 0,85 | +9,2% | +29,8% |
| 50% SPY + 50% momentum top 5 | +16,8% | −30% | 0,77 | +7,5% | +34,6% |
| SPY met trendfilter (200d) | +11,2% | −21% | 0,95 | +8,5% | +15,6% |
| SPY kopen en houden | +15,0% | −34% | 0,88 | +11,1% | +21,7% |

## Conclusie

Zonder overlevingsbias verslaat de momentumstrategie SPY **niet** op een robuuste manier:
2017–2022 duidelijk slechter (o.a. 2018: −25% vs −5%), 2023–2026 duidelijk beter (AI-rally).
Het eerdere voordeel in `backtest_report.md` kwam grotendeels door een met voorkennis gekozen
aandelenlijst. Een sectorlimiet van 25% verlaagde het rendement; de marktfilter verlaagde de
dalingen maar ook het rendement. Een kern van SPY met een momentum-satelliet gaf het beste
evenwicht (iets meer rendement dan SPY, kleinere daling), maar is geen grote voorsprong.
