const { execSync } = require("child_process");

const integration = process.env.INTEGRATION_NAME;

if (!integration) {
  throw new Error(
    "INTEGRATION_NAME is not set. Example: INTEGRATION_NAME=smhialerts"
  );
}

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

    [
      "@semantic-release/exec",
      {
        generateNotesCmd:
          "node .release/generate-notes.js \"${nextRelease.version}\" \"${branch.name}\""
      }
    ],

    [
      "@semantic-release/exec",
      {
        prepareCmd:
          "jq '.version = \"${nextRelease.version}\"' custom_components/" +
          integration +
          "/manifest.json > manifest.tmp && " +
          "mv manifest.tmp custom_components/" +
          integration +
          "/manifest.json && " +
          "cd custom_components && zip -r " +
          integration +
          ".zip " +
          integration
      }
    ],

    [
      "@semantic-release/github",
      {
        draft: true,
        releaseNotesFile: "RELEASE_NOTES.md",
        assets: [
          {
            path: "custom_components/${process.env.INTEGRATION_NAME}.zip",
            label: "${process.env.INTEGRATION_NAME}.zip"
          }
        ]
      }
    ]
  ]
};