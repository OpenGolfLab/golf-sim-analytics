# OpenGolfLab Community Data (read)

The desktop app's **Community dashboard** reads the community's published data
back from OpenGolfLab. It's the read counterpart to the contribution intake — but
unlike the write path (a token-holding Worker into a private repo), the read is
just a **static JSON file** the app GETs.

**What's published is aggregate, not raw.** The file holds one **median point per
(contributor, club)** — each golfer's typical carry/offline/etc. for a club —
never anyone's individual shots. Raw shots stay in OpenGolfLab's private data
repo and are never served. The aggregator
(`opengolflab-data/aggregate.py::build_community_points`) writes this file, and it
is published to the website's public data alongside `summary.json`/`feed.json`.

Set `config.OPENGOLFLAB_COMMUNITY_URL` to the directory that serves it (the
website's public data root); the app appends the filename. Before the aggregator
has published a pool the GET 404s and the dashboard shows its empty state — never
an error.

## Endpoint

```
GET {OPENGOLFLAB_COMMUNITY_URL}/community_points.json
```

A plain static file — no query parameters, no auth. The app fetches the whole
file and filters by club locally (the global Club Filter), so it stays small.

## Response

`200 application/json`:

```json
{
  "count": 2,
  "as_of": "2026-07-16T00:00:00Z",
  "points": [
    {
      "club": "7I",
      "n": 41,
      "carry": 153.2,
      "ball_speed": 115.4,
      "launch_angle": 18.7,
      "offline": 1.1,

      "ball_model": "Pro V1",
      "launch_monitor": "Trackman",
      "contributed": "2026-07-15",
      "display_name": "SteadyFade-3fa2"
    }
  ]
}
```

- **Every numeric value is a median** — this golfer's median for the club, over
  `n` shots. `n` is the shot count behind the median (shown in the hover card and
  used to total shots vs. golfers correctly).
- Field names are the **OpenGolfLab schema** names (same as the contributed
  `shots.csv` header), not the app's internal column names — `community.py` maps
  them. Distances are **yards**, speeds **mph**, spin **rpm**.
- `club` and `carry` are required per point; the client drops rows missing carry.
- A point is emitted only for a (contributor, club) with at least
  `MIN_CLUB_SHOTS` shots — too few and the median isn't trustworthy.
- `count` and `as_of` are informational (shown in the dashboard subtitle).
- For robustness the client also accepts the list under a `shots` key, or a bare
  top-level list.

### Descriptive fields (optional)

These populate the hover card so a dot reads as "RangeRat's 7I, Trackman" instead
of an anonymous point. Each is **optional** — the client renders whichever are
present and omits the rest, so a file carrying none still works (the card falls
back to club + median carry).

| Field | Meaning |
|-------|---------|
| `ball_model` | The ball this golfer played most for the club, e.g. `"Pro V1"`. |
| `launch_monitor` | The monitor model from the contributor's `environment.instrument.model`, e.g. `"Trackman"`. |
| `contributed` | Day-granular `YYYY-MM-DD` of the contributor's latest bundle (the manifest `created_date`). **Never** a full timestamp. |
| `display_name` | The contributor's **public** display name (manifest `display_name`, schema v1.3+). This is the *only* identity field permitted here, and only because it is a name the contributor chose specifically to be shown publicly (see `SCHEMA.md`). |

- **No other contributor identity** may appear — no uuid, real name, email, file
  path, exact timestamp, or handicap. `display_name` is the sole,
  deliberately-public exception; everything else stays anonymized.

## Errors / empty

Any non-200 (including a 404 before the first publish), network failure, timeout,
or malformed body makes the client return an empty frame (logged, never raised);
the dashboard renders an offline/empty state. An empty pool should still be
`200` with `"points": []`.

## Privacy note

Because only **medians** (never raw shots) are published, this is not a step
beyond the aggregates-only main site — it *is* aggregates. A golfer's individual
shots never leave the private data repo; the strongest thing derivable from this
file about a person is "their median 7I carries 158 yds", under the public name
they chose. Only medians from sessions a user explicitly contributed enter it.
