# Backtest regelstrategie

_Gegenereerd 2026-10-23. Dezelfde regels als de agent (`agent/rules.py`); plan op slotkoers, uitvoering op opening volgende dag; kosten 0,05% per transactie; startbedrag $10.000; pauzeregel −15% met reset na 20 beursdagen._

**Waarschuwing:** de aandelenlijsten zijn met kennis van vandaag gekozen (overlevingsbias), dus de resultaten zijn optimistisch. Dividenden zitten in de koersen (gecorrigeerd).

## Volledig 2017–2026

| Variant | Totaal | Per jaar | Max. daling | Sharpe | Kosten | Omzet/jaar |
|---|---:|---:|---:|---:|---:|---:|
| Huidig (top 10, max 10%, dagelijks) | +459% | +19.3% | −21% | 1.13 | $3,419 | 69.9× |
| Geconcentreerd (top 5, max 20%) | +1068% | +28.6% | −24% | 1.29 | $6,838 | 139.9× |
| Maandelijks herbalanceren | +431% | +18.6% | −30% | 0.99 | $681 | 13.9× |
| Sneller (100d-trend, 6m-momentum) | +242% | +13.4% | −19% | 0.90 | $4,252 | 87.0× |
| Breder universum (+50 large caps) | +718% | +24.0% | −28% | 1.00 | $4,906 | 100.3× |
| Breder + geconcentreerd (top 5, max 20%) | +797% | +25.2% | −35% | 0.90 | $5,246 | 107.3× |
| Huidig + buffer 10 + band 3% | +465% | +19.4% | −20% | 1.13 | $796 | 16.3× |
| Top 5, max 20% + buffer 5 + band 3% | +660% | +23.1% | −24% | 1.09 | $946 | 19.4× |
| Breder, top 10 + buffer 10 + band 3% | +583% | +21.7% | −29% | 0.93 | $850 | 17.4× |
| Breder, top 5, max 20% + buffer 5 + band 3% | +923% | +26.8% | −36% | 0.93 | $1,128 | 23.1× |
| **SPY kopen en houden** | +298% | +15.2% | −34% | 0.88 | $0 | — |

## Deel 1 (2017–2022)

| Variant | Totaal | Per jaar | Max. daling | Sharpe | Kosten | Omzet/jaar |
|---|---:|---:|---:|---:|---:|---:|
| Huidig (top 10, max 10%, dagelijks) | +157% | +17.1% | −21% | 0.97 | $1,271 | 42.5× |
| Geconcentreerd (top 5, max 20%) | +256% | +23.6% | −24% | 1.09 | $2,182 | 72.9× |
| Maandelijks herbalanceren | +169% | +18.0% | −30% | 0.90 | $231 | 7.7× |
| Sneller (100d-trend, 6m-momentum) | +114% | +13.6% | −18% | 0.88 | $1,811 | 60.5× |
| Breder universum (+50 large caps) | +178% | +18.6% | −26% | 0.87 | $2,183 | 72.9× |
| Breder + geconcentreerd (top 5, max 20%) | +152% | +16.7% | −35% | 0.71 | $2,111 | 70.5× |
| Huidig + buffer 10 + band 3% | +189% | +19.4% | −20% | 1.07 | $329 | 11.0× |
| Top 5, max 20% + buffer 5 + band 3% | +203% | +20.3% | −24% | 0.96 | $339 | 11.3× |
| Breder, top 10 + buffer 10 + band 3% | +163% | +17.5% | −26% | 0.83 | $454 | 15.2× |
| Breder, top 5, max 20% + buffer 5 + band 3% | +167% | +17.8% | −34% | 0.74 | $529 | 17.7× |
| **SPY kopen en houden** | +88% | +11.1% | −34% | 0.64 | $0 | — |

## Deel 2, ongezien (2023–2026)

| Variant | Totaal | Per jaar | Max. daling | Sharpe | Kosten | Omzet/jaar |
|---|---:|---:|---:|---:|---:|---:|
| Huidig (top 10, max 10%, dagelijks) | +120% | +23.1% | −19% | 1.46 | $824 | 43.5× |
| Geconcentreerd (top 5, max 20%) | +237% | +37.8% | −23% | 1.66 | $1,313 | 69.3× |
| Maandelijks herbalanceren | +99% | +19.9% | −20% | 1.23 | $168 | 8.9× |
| Sneller (100d-trend, 6m-momentum) | +67% | +14.5% | −18% | 1.00 | $1,205 | 63.6× |
| Breder universum (+50 large caps) | +198% | +33.4% | −27% | 1.20 | $959 | 50.6× |
| Breder + geconcentreerd (top 5, max 20%) | +263% | +40.5% | −34% | 1.16 | $1,247 | 65.9× |
| Huidig + buffer 10 + band 3% | +98% | +19.9% | −20% | 1.30 | $169 | 8.9× |
| Top 5, max 20% + buffer 5 + band 3% | +157% | +28.3% | −23% | 1.35 | $212 | 11.2× |
| Breder, top 10 + buffer 10 + band 3% | +166% | +29.5% | −29% | 1.09 | $159 | 8.4× |
| Breder, top 5, max 20% + buffer 5 + band 3% | +295% | +43.7% | −36% | 1.19 | $234 | 12.4× |
| **SPY kopen en houden** | +113% | +22.1% | −19% | 1.42 | $0 | — |

## Rendement per jaar (volledige periode)

| Variant | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Huidig (top 10, max 10%, dagelijks) | +30% | +5% | +27% | +26% | +19% | -0% | +30% | +44% | +6% | +10% |
| Geconcentreerd (top 5, max 20%) | +33% | +28% | +20% | +36% | +21% | +6% | +35% | +74% | +20% | +16% |
| Maandelijks herbalanceren | +34% | +7% | +21% | +20% | +21% | +6% | +22% | +44% | +4% | +7% |
| Sneller (100d-trend, 6m-momentum) | +23% | +3% | +19% | +23% | +31% | -11% | +32% | +19% | +3% | -2% |
| Breder universum (+50 large caps) | +35% | +8% | +24% | +46% | +21% | -13% | +19% | +32% | +14% | +64% |
| Breder + geconcentreerd (top 5, max 20%) | +44% | -7% | +33% | +66% | -8% | -7% | +28% | +52% | +2% | +78% |
| Huidig + buffer 10 + band 3% | +33% | +8% | +26% | +27% | +24% | +1% | +29% | +41% | +3% | +4% |
| Top 5, max 20% + buffer 5 + band 3% | +26% | +12% | +31% | +36% | +24% | -3% | +40% | +66% | +6% | +1% |
| Breder, top 10 + buffer 10 + band 3% | +44% | +0% | +18% | +54% | +10% | -9% | +21% | +35% | +4% | +54% |
| Breder, top 5, max 20% + buffer 5 + band 3% | +37% | -15% | +34% | +71% | +4% | -4% | +24% | +49% | -8% | +125% |
| **SPY kopen en houden** | +21% | -5% | +31% | +18% | +29% | -18% | +26% | +25% | +18% | +14% |
