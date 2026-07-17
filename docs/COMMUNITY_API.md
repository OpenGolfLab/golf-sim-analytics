# OpenGolfLab Community Read API

The desktop app's **Community dashboard** reads shared, anonymized shots back from
OpenGolfLab through this endpoint. It is the read counterpart to the write-only
intake Worker (`opengolflab-data/worker`). **This endpoint does not exist yet —
it must be built and deployed separately** (a new route on the Worker, backed by
a public pool of shots that contributors opted to share). The desktop client
(`community.py`) already speaks this contract; until the endpoint is live and
`config.OPENGOLFLAB_COMMUNITY_URL` is set, the dashboard shows an offline state.

## Endpoint

```
GET {OPENGOLFLAB_COMMUNITY_URL}/shots?club=7I&limit=2000
```

Query parameters:

| Param   | Required | Meaning                                                        |
|---------|----------|----------------------------------------------------------------|
| `limit` | no       | Max shots to return (client sends 2000). Server may cap lower.  |
| `club`  | no       | Restrict to one canonical club label (`Dr`, `3W`, `7I`, `Sw`…). |

## Response

`200 application/json`:

```json
{
  "count": 2,
  "as_of": "2026-07-16T00:00:00Z",
  "shots": [
    {
      "club": "7I",
      "ball_speed": 115.4,
      "club_speed": 79.9,
      "launch_angle": 18.7,
      "back_spin": 6280,
      "carry": 153.2,
      "total": 162.0,
      "offline": 1.1,
      "smash": 1.44,
      "apex": 86
    }
  ]
}
```

- Field names are the **OpenGolfLab schema** names (same as the contributed
  `shots.csv` header), not the app's internal column names — `community.py` maps
  them. Distances are **yards**, speeds **mph**, spin **rpm**, apex **feet**.
- `club` and `carry` are required per shot; the client drops rows missing carry.
- **No contributor identity** may appear in the payload — no uuid, name, file
  path, timestamp, or handicap tied to an individual shot. The pool is a mixed,
  anonymized shot set.
- `count` and `as_of` are informational (shown in the dashboard subtitle).

## Errors / empty

Any non-200, network failure, timeout, or malformed body makes the client return
an empty frame (logged, never raised); the dashboard renders an offline/empty
state. An empty pool should still return `200` with `"shots": []`.

## Privacy note

This is a step beyond the aggregates-only publication of the main site: it shares
**shot-level** rows publicly. Only shots a user explicitly pushed via the
Contribute panel's round picker should ever enter this pool, and every row must
be stripped of anything identifying before it is served here.
