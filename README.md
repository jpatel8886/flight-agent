# Flight price monitor

Checks one-way fares several times a day, tries layover-city tricks, emails you
when the price drops, and publishes a small dashboard on GitHub Pages. Runs
entirely on free GitHub infrastructure.

## How it searches

Each run, for every entry in `config.yaml`:

1. **Direct search**: origin → destination on
   - Google Flights (scraped via `fast-flights`, no key)
   - Skiplagged (public search API, no key; includes Kiwi virtual-interlining and hidden-city fares)
   - Google Flights via SerpApi (optional, if `SERPAPI_KEY` is set; a reliable fallback if scraping gets blocked)
2. **Single ticket via hub**: Google Flights constrained to connect through each
   hub in `hubs:` (DXB, DOH, AUH, IST, RUH, JED, …).
3. **Self-transfer (2 tickets)**: prices origin → hub and hub → destination
   separately and pairs legs with a safe connection (default 3h–24h). Second-leg
   dates follow from when the first leg lands. A hub is pruned when its first leg
   alone already costs more than the best fare found, which saves requests.

Results are de-duplicated across sources (same flights → cheapest kept, with
"also seen on" prices). Itineraries longer than `max_trip_hours` are dropped.

**Expedia, Skyscanner and Kayak** don't offer public search APIs and block
scrapers aggressively, so they're never searched directly. Instead, every result
comes with pre-filled deep links to them (and to Google Flights/Skiplagged), so
you can check the fare there and book.

## Setup (about 10 minutes)

1. **Create a GitHub repo** (e.g. `flight-agent`) and push this folder to it.
2. **Gmail app password**: Google Account → Security → 2-Step Verification →
   *App passwords* → create one (16 characters).
3. **Repo secrets**: Settings → Secrets and variables → Actions → *New repository secret*:
   | Secret | Value |
   |---|---|
   | `GMAIL_ADDRESS` | your Gmail address |
   | `GMAIL_APP_PASSWORD` | the app password from step 2 |
   | `EMAIL_TO` | optional, defaults to `GMAIL_ADDRESS` |
   | `SERPAPI_KEY` | optional, free key from serpapi.com |
4. **Dashboard**: Settings → Pages → *Deploy from a branch* → `main` / `/docs`.
   It will be at `https://<user>.github.io/<repo>/`.
5. **Edit `config.yaml`** (origin, destination, date, target price) and push.
6. Actions tab → *Monitor flight prices* → **Run workflow** to do the first check now.
   After that it runs hourly (`cron` in `.github/workflows/monitor.yml`).

> **Privacy:** GitHub Pages sites are public. The page is marked `noindex`, but
> anyone with the URL can see the route and date you're watching. On a free plan,
> Pages requires a public repo, so the config is public too. Secrets stay private.

## Ranking

Options are ranked by **best value**, not raw price: price + `value_per_hour` for
each hour of travel + `per_stop_penalty` per layover + extra for separate tickets
or hidden-city. Tune it under `ranking:` in `config.yaml` (all zeros = cheapest first).
The cheapest fare is always shown too, tagged "Cheapest".

## Emails

The search runs **hourly**, but email goes out at most **4 times a day**: one
combined email on the first run after each `alerts.send_hours_local` time
(default 7:00, 12:00, 17:00, 21:00 in `utc_offset_hours`, which is set to IST).
Each email says whether the best option got better or worse since the last one,
and flags any fare at or below `target_price`.

## Priority Pass lounges

For every layover airport, the dashboard and emails show Priority Pass lounges:
name, terminal, hours and member star rating (Priority Pass publishes ratings and
rating counts, not written reviews). Landside lounges, which you can't reach on a
connection, are excluded. Data comes from prioritypass.com and is cached in
`docs/data/lounges.json` (airport list 90 days, lounge details 30 days), so
normal runs make few or no extra requests.

## Run locally

```bash
pip install -r requirements.txt
python -m unittest discover -s tests
python -m flightagent --no-email          # writes docs/data/*.json
python -m http.server -d docs 8000        # open http://localhost:8000
```

Set `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` in the environment to test email.

## Caveats

- Google Flights and Skiplagged are scraped through unofficial endpoints. They
  can change or rate-limit at any time. Failures show up under "lookup issues"
  on the dashboard, and the run still completes with whatever succeeded. Adding
  `SERPAPI_KEY` gives a stable fallback for the main search.
- **Self-transfer** fares are two separate tickets. If leg 1 is late, the airline
  on leg 2 owes you nothing. You'll also need to collect bags and re-check them,
  and may need a transit visa for the hub country.
- **Hidden-city** fares (Skiplagged): you get off at the layover. Carry-on only,
  one-way only, and airlines discourage it.
- Times shown are local to each airport.
