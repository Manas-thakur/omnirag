// @ts-check
import starlight from "@astrojs/starlight"
import { defineConfig } from "astro/config"
import starlightLinksValidator from "starlight-links-validator"

const repo = "https://github.com/Manas-thakur/omnirag"

// https://astro.build/config
export default defineConfig({
  site: "https://manas-thakur.github.io",
  base: "/omnirag",
  trailingSlash: "always",
  // Screenshots, the changelog and the contributing guide live outside site/.
  vite: { server: { fs: { allow: [".."] } } },
  integrations: [
    starlight({
      title: "OmniRAG",
      description:
        "Self-hosted, multi-modal RAG: ask questions across documents, code, tables, images and transcripts and get answers that cite their sources.",
      logo: { src: "./src/assets/logo.svg", replacesTitle: false },
      favicon: "/favicon.svg",
      social: [{ icon: "github", label: "GitHub", href: repo }],
      editLink: { baseUrl: `${repo}/edit/main/site/` },
      lastUpdated: false,
      customCss: ["./src/styles/fonts.css", "./src/styles/starlight.css"],
      plugins: [starlightLinksValidator({ errorOnRelativeLinks: true })],
      sidebar: [
        {
          label: "Start here",
          items: [
            { label: "Introduction", slug: "docs" },
            { label: "Installation", slug: "docs/installation" },
            { label: "Quickstart", slug: "docs/quickstart" },
          ],
        },
        {
          label: "Concepts",
          items: [
            { label: "Knowledge bases", slug: "docs/concepts/knowledge-bases" },
            { label: "Modalities", slug: "docs/concepts/modalities" },
            { label: "Chunking", slug: "docs/concepts/chunking" },
            { label: "Hybrid retrieval", slug: "docs/concepts/retrieval" },
            { label: "Answers and citations", slug: "docs/concepts/citations" },
            { label: "Scoping", slug: "docs/concepts/scoping" },
          ],
        },
        {
          label: "Guides",
          items: [
            { label: "Web app", slug: "docs/guides/web-app" },
            { label: "Ollama and OpenAI-compatible models", slug: "docs/guides/models" },
            { label: "Deployment", slug: "docs/guides/deployment" },
          ],
        },
        {
          label: "Reference",
          items: [
            { label: "CLI", slug: "docs/reference/cli" },
            { label: "HTTP API", slug: "docs/reference/http-api" },
            { label: "Python API", slug: "docs/reference/python-api" },
            { label: "Configuration", slug: "docs/reference/configuration" },
          ],
        },
        {
          label: "Project",
          items: [
            { label: "Troubleshooting and FAQ", slug: "docs/troubleshooting" },
            { label: "Changelog", slug: "docs/changelog" },
            { label: "Contributing", slug: "docs/contributing" },
          ],
        },
      ],
    }),
  ],
})
