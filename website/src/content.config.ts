import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

// Blog collection — Markdown files in src/content/blog/.
// Uses Astro's content-layer glob loader (Astro 5+).
const blog = defineCollection({
  loader: glob({ base: "./src/content/blog", pattern: "**/*.{md,mdx}" }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    pubDate: z.coerce.date(),
    updatedDate: z.coerce.date().optional(),
    // Path under /public, e.g. "/images/blog/intro.jpg". Optional.
    heroImage: z.string().optional(),
    tags: z.array(z.string()).default([]),
    draft: z.boolean().default(false),
  }),
});

export const collections = { blog };
