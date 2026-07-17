# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately through GitHub's **[Report a vulnerability](https://github.com/OpenGolfLab/golf-sim-analytics/security/advisories/new)**
button (Security → Advisories), which opens a private advisory only the
maintainers can see. Include:

- what the issue is and its impact,
- steps to reproduce (or a proof of concept), and
- affected version / commit.

We aim to acknowledge reports within a few days and will keep you updated on a
fix and disclosure timeline.

## Scope

Golf Sim Analytics is a local Windows desktop app. The areas most worth
scrutiny:

- **The OpenGolfLab contribution path** (`contribute.py`) — it must only ever
  send anonymized, opt-in shot metrics, never personally identifying data.
- **The community read client** (`community.py`) — it fetches remote data; it
  must fail safe (empty state) and never execute or trust remote content beyond
  plotting numbers.
- Local file handling for GSPro data and CSV import.

The intake and community **server-side** components live in separate OpenGolfLab
repositories; report issues there against those projects.

## Good to know

- The app reads GSPro's files but never writes to them, and it stores your data
  only in local files next to the app.
- Contribution is off unless you turn it on, and you choose which rounds are
  shared.
