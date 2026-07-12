# OpenGolfLab — website

Marketing site for **OpenGolfLab** (opengolflab.com) and its first product,
**Golf Sim Analytics**. Built with [Astro](https://astro.build), static output,
deployed free to GitHub Pages with a custom domain.

- Dark, data-forward design · vanilla Astro components + scoped CSS
- Blog via Content Collections + RSS + sitemap
- No server-side anything, no heavy UI frameworks

---

## Quick start (local dev)

Requires **Node 18.20+ / 20+** and npm.

```bash
npm install
npm run dev      # http://localhost:4321
```

Other scripts:

```bash
npm run build    # production build → ./dist
npm run preview  # serve the built site locally
```

---

## Project structure

```
.
├── .github/workflows/deploy.yml   # GitHub Pages CI
├── public/
│   ├── CNAME                       # custom domain (opengolflab.com)
│   ├── favicon.svg                 # inline shot-trace logo mark
│   ├── robots.txt
│   └── images/
│       ├── screenshots/            # drop app screenshots here (exact names)
│       └── blog/                   # blog hero images
├── src/
│   ├── consts.ts                   # ⭐ single source of truth (repo, URLs, nav)
│   ├── content.config.ts           # blog collection schema
│   ├── components/                 # Nav, Footer, Logo, BaseHead, Screenshot…
│   ├── layouts/                    # BaseLayout, BlogPost
│   ├── content/blog/               # Markdown posts
│   ├── pages/                      # index, download, lab, 404, blog/, rss.xml
│   └── styles/global.css           # design system (CSS custom properties)
└── astro.config.mjs                # site URL + sitemap
```

### One thing to edit before you ship

Open **`src/consts.ts`** and replace the `OWNER/REPO` placeholder with your real
GitHub repo:

```ts
export const GITHUB_REPO = "opengolflab/golf-sim-analytics";
```

That constant drives the download button (`/releases/latest`), the GitHub links,
and the "watch the repo" CTA — change it once, everywhere updates.

---

## Adding a blog post

1. Create a Markdown file in `src/content/blog/`, e.g. `my-post.md`.
   The filename becomes the URL slug: `/blog/my-post/`.
2. Add frontmatter (schema enforced in `src/content.config.ts`):

   ```markdown
   ---
   title: "My post title"
   description: "One-sentence summary used for SEO and the blog index."
   pubDate: 2026-08-01
   heroImage: "/images/blog/my-post.jpg"   # optional
   tags: ["release", "product"]            # optional
   draft: false                            # optional; true hides it
   ---

   Your content in **Markdown**.
   ```

3. Save. It appears automatically on `/blog`, in the RSS feed, and in the sitemap.
   The newest post is featured at the top of the index.

Set `draft: true` to keep a post out of the build while you work on it.

---

## Cutting a release (of the app)

The website's Download button always points at
`https://github.com/OWNER/REPO/releases/latest`, so you never touch the site to
ship a new version — just publish a GitHub Release on the **app** repo:

1. Build the Windows installer (`.exe`) in the app project.
2. On the app repo: **Releases → Draft a new release**.
3. Create a tag (e.g. `v1.2.0`), add notes, and **attach the `.exe`** as a
   release asset.
4. **Publish**. `/releases/latest` now serves it — the site updates with zero
   changes.

Optionally announce it with a new blog post here (see above).

---

## Deploying to GitHub Pages + custom domain

### 1. Push to GitHub

Put this project in a repo (root of the repo = this folder). The included
workflow `.github/workflows/deploy.yml` builds with the official
[`withastro/action`](https://github.com/withastro/action) and deploys on every
push to `main`.

### 2. Turn on Pages

Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.
(That's the only setting to flip — no branch selection needed.)

Push to `main` once; the **Deploy to GitHub Pages** workflow runs and publishes.

### 3. Custom domain DNS

`public/CNAME` already contains `opengolflab.com`, so GitHub will claim the
apex domain on deploy. At your DNS provider, add these records:

**Apex (`opengolflab.com`) — four A records to GitHub Pages:**

| Type | Host / Name | Value           |
| ---- | ----------- | --------------- |
| A    | `@`         | `185.199.108.153` |
| A    | `@`         | `185.199.109.153` |
| A    | `@`         | `185.199.110.153` |
| A    | `@`         | `185.199.111.153` |

**`www` subdomain — CNAME to your Pages host:**

| Type  | Host / Name | Value                     |
| ----- | ----------- | ------------------------- |
| CNAME | `www`       | `OWNER.github.io.`        |

> Replace `OWNER` with your GitHub username or org (e.g. `opengolflab.github.io.`).
> If your provider supports it, adding **AAAA** records is recommended too:
> `2606:50c0:8000::153`, `2606:50c0:8001::153`, `2606:50c0:8002::153`,
> `2606:50c0:8003::153` (all on `@`).

### 4. Finish in GitHub

- **Settings → Pages → Custom domain**: confirm `opengolflab.com` is set
  (the `CNAME` file usually populates this automatically).
- Tick **Enforce HTTPS** once the certificate is issued (can take a few minutes
  after DNS propagates).

DNS changes can take anywhere from minutes to a few hours to propagate.

---

## Notes

- **Fonts** load from Google Fonts with `preconnect` + `display=swap` (Space
  Grotesk, Inter, JetBrains Mono). To fully self-host, download the woff2 files
  into `public/fonts/` and swap the `<link>` tags in
  `src/components/BaseHead.astro` for local `@font-face` rules.
- **Screenshots** are lazy-loaded and aspect-ratio-locked, so missing images
  never cause layout shift. Add real ones under `public/images/screenshots/`
  using the filenames in that folder's README.
- The site is fully static — safe to host anywhere (Netlify, Cloudflare Pages,
  S3). Just keep `site` in `astro.config.mjs` in sync with the domain.

---

© 2026 OpenGolfLab. Independent project — not affiliated with GSPro.
