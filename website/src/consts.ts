// ---------------------------------------------------------------------------
// Site-wide constants. Change these in ONE place.
// ---------------------------------------------------------------------------

/**
 * GitHub repository that hosts the app releases, in "OWNER/REPO" form.
 * ⇩⇩⇩  REPLACE THIS with your real repo, e.g. "opengolflab/golf-sim-analytics".
 */
export const GITHUB_REPO = "OWNER/REPO";

/** Full URL to the GitHub repo. */
export const GITHUB_URL = `https://github.com/${GITHUB_REPO}`;

/** "Download the latest release" link — always points at the newest release. */
export const LATEST_RELEASE_URL = `${GITHUB_URL}/releases/latest`;

/** Watch/star the repo (used on the Lab page as an email-free CTA). */
export const GITHUB_WATCH_URL = `${GITHUB_URL}/subscription`;

/** Site identity. */
export const SITE_TITLE = "OpenGolfLab";
export const SITE_TAGLINE = "Every shot. Every insight.";
export const SITE_DESCRIPTION =
  "OpenGolfLab builds open, community-driven golf simulator analytics. Golf Sim Analytics is a free Windows app for GSPro users — 15 interactive dashboards, deep per-shot metrics, and PGA Tour benchmarks. Local-first and private.";

/** Canonical production origin (no trailing slash). */
export const SITE_URL = "https://opengolflab.com";

/** Product facts reused across pages. */
export const PRODUCT_NAME = "Golf Sim Analytics";
export const PRODUCT_OS = "Windows 10 / 11 (64-bit)";
export const PRODUCT_PRICE = "0"; // free

/** Top navigation. */
export const NAV_LINKS = [
  { href: "/", label: "Home" },
  { href: "/download", label: "Download" },
  { href: "/blog", label: "Blog" },
  { href: "/lab", label: "Lab" },
] as const;
