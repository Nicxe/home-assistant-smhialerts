const fs = require("fs");
const path = require("path");

const COMPONENTS_DIR = process.env.COMPONENTS_DIR || "custom_components";

function detectSingleIntegrationName() {
  try {
    const dir = path.join(process.cwd(), COMPONENTS_DIR);
    const entries = fs
      .readdirSync(dir, { withFileTypes: true })
      .filter((e) => e.isDirectory())
      .map((e) => e.name)
      .filter((name) => !name.startsWith("."));

    // If exactly one folder exists under custom_components, assume it is the integration.
    if (entries.length === 1) return entries[0];

    return null;
  } catch (err) {
    return null;
  }
}

const integration =
  process.env.INTEGRATION_NAME ||
  detectSingleIntegrationName();

if (!integration) {
  throw new Error(
    "Could not determine integration name. Set INTEGRATION_NAME (e.g. INTEGRATION_NAME=smhialerts) or ensure exactly one folder exists under custom_components."
  );
}

const manifestPath = path.join(COMPONENTS_DIR, integration, "manifest.json");
const zipPath = path.join(COMPONENTS_DIR, `${integration}.zip`);

module.exports = {
  tagFormat: "v${version}",

  branches: [
    "main",
    { name: "beta", prerelease: true }
  ],

  plugins: [
    [
      "@semantic-release/commit-analyzer",
      { preset: "conventionalcommits" }
    ],

    // Generate RELEASE_NOTES.md via your script (avoids conventional-changelog date parsing issues)
    [
      "@semantic-release/exec",
      {
        // Note: semantic-release variables must be passed as literals, not evaluated by Node.
        // We escape ${...} so semantic-release can substitute them at runtime.
        generateNotesCmd: `node .release/generate-notes.js "\${nextRelease.version}" "\${branch.name}" "${integration}"`
      }
    ],

    // 1) bump manifest.json version  2) build zip asset
    [
      "@semantic-release/exec",
      {
        prepareCmd: `set -euo pipefail; \
          tmpfile=$(mktemp); \
          jq --arg version "\${nextRelease.version}" '.version = $version' "${manifestPath}" > "$tmpfile"; \
          mv "$tmpfile" "${manifestPath}"; \
          (cd "${COMPONENTS_DIR}" && zip -r "${integration}.zip" "${integration}")`
      }
    ],

    [
      "@semantic-release/github",
      {
        draft: true,
        releaseNotesFile: "RELEASE_NOTES.md",
        assets: [
          {
            path: zipPath,
            label: `${integration}.zip`
          }
        ]
      }
    ]
  ]
};