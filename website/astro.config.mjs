// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

// Production URL. Must match the custom domain in public/CNAME.
// This drives canonical URLs, the sitemap, and the RSS feed.
export default defineConfig({
  site: "https://opengolflab.com",
  integrations: [sitemap()],
  // Static output is the default: no adapter, no SSR, no server code.
  build: {
    // Emit /page/index.html so URLs are clean (/download, /blog, ...).
    format: "directory",
  },
});
