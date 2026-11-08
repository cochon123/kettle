# Data sources

**Every number on screen is real.** This is where each one comes from.

| Data | Use in Kettle | Source | Licence / terms | In repo |
|---|---|---|---|---|
| REFIT Electrical Load Measurements (cleaned), 20 UK homes, 2013–2015, 8 s | Detector accuracy, false check-ins per home per month, Margaret's learned mornings (House 11, single occupant), replayed map homes | Murray, Stankovic & Stankovic (2017), Sci. Data 4:160122, [doi:10.1038/sdata.2016.122](https://doi.org/10.1038/sdata.2016.122); download: University of Strathclyde (`CLEAN_REFIT_081116.7z`) | CC BY 4.0 | derived results only: `data/refit/` |
| AESO Current Supply Demand (live) | Live Alberta Internal Load, generation, contingency reserve (cold mode ring) | http://ets.aeso.ca/ets_web/ip/Market/Reports/CSDReportServlet | AESO public report | fetched live |
| AESO Actual/Forecast, Jan 10–16 2024 (hourly) | Jan 13 2024 replay: pool price, Alberta Internal Load | `ActualForecastWMRQHReportServlet` | AESO public report | `data/aeso/actual_forecast_2024-01-10_2024-01-16.csv` |
| AESO Historical System Marginal Price, Jan 13 2024 | Replay: every price change | `HistoricalSystemMarginalPriceReportServlet` | AESO public report | `data/aeso/smp_2024-01-13.csv` |
| ECCC historical hourly, CALGARY INTL A (station 50430), Jan 2024 | Replay temperature, wind chill | climate.weather.gc.ca bulk data | Open Government Licence – Canada | `data/eccc/calgary_intl_hourly_2024-01.csv` |
| ECCC city page weather, Calgary (live) | Cold mode temperature | `api.weather.gc.ca/collections/citypageweather-realtime/items/ab-52` | Open Government Licence – Canada | fetched live |
| ECCC weather alerts (live, Calgary bbox) | Cold mode trigger (extreme cold warning) | `api.weather.gc.ca/collections/weather-alerts` | Open Government Licence – Canada | fetched live |
| Jan 13 2024 timeline | 15:30 Grid Alert (EEA3), 18:44 emergency text alert, 100→200 MW drop, 20:40 end | [AESO newsroom](https://aeso.ca/aeso/newsroom/aeso-thanks-albertans-for-quick-response-to-call-for-power-conservation/), [Power Advisory](https://www.poweradvisoryllc.com/reports/january-2024-supply-shortfall-in-alberta) | quoted facts | `data/jan13_2024.json` |
| 42% of Canadians aged 85+ live alone | Pitch | [StatCan, The Daily, July 13 2022](https://www150.statcan.gc.ca/n1/daily-quotidien/220713/dq220713a-eng.htm) | – | – |
| 80% didn't use their call alarm | Pitch | [Fleming & Brayne, BMJ 2008](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2590903/) | – | – |
| Zojirushi i-Pot (since 2001) | Pitch precedent | [Zojirushi Mimamori Hotline](https://www.zojirushi.co.jp/corp/sustainable-action/mimamori.html) | – | – |

Refresh the archived AESO and ECCC files with `.venv/bin/python scripts/fetch_real_data.py`. Re-run the evaluation with `.venv/bin/python -m kettle.eval.refit`. It needs the REFIT CSVs locally; see [refit-evaluation.md](refit-evaluation.md).

**Removed claim:** an early brief said reserves "fell to about 10 MW" on Jan 13 2024. Neither AESO's statement nor Power Advisory's report gives an operating-reserve figure, so we don't show or say it.

**Timezone note:** Calgary times use the IANA zone `America/Edmonton`. AESO and ECCC 2024 data are MST (UTC−7). Under Alberta's Official Time Act (June 2026), the province has stayed on "Alberta Time" (ABT, UTC−6) since November 1 2026. tzdata 2026c+ labels it "CST", which is why the event portal says ABT and Devpost says CST for the same deadline.
