# Prompt for Opus: OpenGolfLab website

Build a complete, production-ready static website for **OpenGolfLab** (opengolflab.com), deployed free on **GitHub Pages** with a custom domain. Generate every file in one shot — I should be able to `git push` and have a working site.

## Brand & product context

OpenGolfLab is a new brand for open, community-driven golf simulator analytics. Its first product is **Golf Sim Analytics** — a free Windows desktop app for [GSPro](https://gsprogolf.com/) simulator users. Tagline: **"Every shot. Every insight."**

What the app does (use this for the landing page copy — tighten, don't invent features):

- **Zero-click data capture.** GSPro's Practice Range CSV exports are picked up from the Desktop automatically — no import buttons. Live rounds are tracked in real time from GSPro's round file and archive themselves when the round ends.
- **15 interactive dashboards** across six categories: Metrics (Dispersion, Trajectory, Club Gapping, Swing Efficiency, Shot Quality, Shot & Club Trends), Optimization (Launch & Spin, Session Comparison, Shot Shape), Club Fitting (adapter A/B testing with live shot capture), Speed Training (cruising speed, fatigue curve, long-term progression), On-Course (automatic scorecards), and Live (real-time dispersion).
- **Deep per-shot analytics** — hover any point for carry, ball speed, launch, descent, spin, smash factor, each flagged against that club's ideal window.
- **Benchmarks** — overlay PGA Tour averages or any handicap level (5–20) with one click.
- **Built-in fitting bay** — compare shafts/adapter settings head-to-head.
- **Local-first, private** — all data lives in Parquet files next to the app; nothing leaves the user's machine. Free, no account required.
- Windows-only. Distributed as a normal installer (per-user, no admin rights). The exe is unsigned, so first run shows a SmartScreen warning (More info → Run anyway) — the download page must explain this honestly and reassuringly.

## Tech requirements

- **Astro** (latest stable), static output, no server-side anything.
- **Deploy:** GitHub Actions workflow (`.github/workflows/deploy.yml`) using the official `withastro/action` → GitHub Pages. Include the workflow file.
- **Custom domain:** `public/CNAME` containing `opengolflab.com`. Set `site: "https://opengolflab.com"` in `astro.config.mjs`. In a comment or README section, list the exact DNS records I need (4 apex A records for GitHub Pages + `www` CNAME) and the repo settings to flip.
- **Blog:** Astro Content Collections. Markdown posts in `src/content/blog/`, typed schema (title, description, pubDate, optional heroImage, tags). Blog index page + post layout with clean typography. Include 2 sample posts: an intro post announcing OpenGolfLab and the app.
- **RSS feed** (`@astrojs/rss`) and **sitemap** (`@astrojs/sitemap`).
- No heavy UI frameworks. Vanilla Astro components + scoped CSS (or plain CSS with custom properties). Minimal client-side JS.
- Include `README.md` covering: local dev, adding a blog post, cutting a release, DNS setup.

## Pages

1. **Home (`/`)** — Hero with tagline, one-line pitch, primary CTA "Download for Windows" + secondary "Read the blog". Feature grid drawn from the product context above. A screenshots section with placeholder images (`/images/screenshots/home.jpg`, `dispersion.jpg`, `gapping_benchmarks.jpg`, `live.jpg`, `speed_training.jpg` — I'll drop in real ones; use those exact paths and give them descriptive alt text). A "How it works" strip (Export/Play → Auto-ingest → Explore dashboards). A section teasing the community analytics vision (see page 4).
2. **Download (`/download`)** — Big button linking to `https://github.com/OWNER/REPO/releases/latest` (leave `OWNER/REPO` as an obvious placeholder constant defined in one place, e.g. `src/consts.ts`). System requirements (Windows 10/11, GSPro). Install steps including the SmartScreen note. FAQ: is it free (yes), does my data leave my machine (no), does it work with launch monitors other than GSPro (it works with anything that plays through GSPro).
3. **Blog (`/blog`)** — index of posts, newest first, plus individual post pages at `/blog/[slug]`.
4. **Lab (`/lab`)** — the community analytics hub, launching as a credible "coming soon". Explain the vision: an open framework where sim golfers contribute anonymized ball and club metrics, producing community-driven analytics — real-world ball comparisons, club gapping distributions by handicap, launch/spin norms. Include an email-free call to action (e.g., "follow the blog / watch the GitHub repo") — no newsletter backend. Structure the page so real data tables/charts can slot in later.
5. **404** page on brand.

Shared layout: sticky top nav (logo wordmark "OpenGolfLab", Home, Download, Blog, Lab), footer with GitHub link placeholder and © 2026 OpenGolfLab.

## Design

- **Dark, data-forward.** It should feel like a simulator analytics tool: near-black background (#0d1117-ish), high-contrast type, a golf-green accent (electric/fairway green) for CTAs and data highlights, subtle grid or dot-matrix texture in the hero evoking a launch-monitor readout.
- Typography: a strong geometric/technical sans for headings (Google Fonts, self-host or preload), readable body font. Tabular numerals where numbers appear.
- Tasteful micro-details welcome (e.g., stat chips like "SMASH 1.49" in the hero), but keep it fast: aim Lighthouse ≥95, no layout shift, lazy-load screenshots.
- Fully responsive. Accessible: semantic HTML, visible focus states, WCAG AA contrast.
- Create a simple inline SVG logo mark (abstract shot-trace/dispersion motif) — no external image dependency, and use it for favicon too.

## SEO

Per-page titles/descriptions, Open Graph + Twitter meta, canonical URLs, JSON-LD (`SoftwareApplication` on the download page, `BlogPosting` on posts).

## Output

Emit the complete file tree, then every file's full contents. No placeholders like "add styles here" — everything must work after `npm install && npm run dev`.
