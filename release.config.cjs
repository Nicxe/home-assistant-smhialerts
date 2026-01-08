const fs = require("fs");
const path = require("path");

const mainTemplate = fs.readFileSync(
  path.join(__dirname, ".release", "release-notes.hbs"),
  "utf8"
);

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
      "@semantic-release/release-notes-generator",
      {
        preset: "conventionalcommits",
        writerOpts: {
          mainTemplate,
          transform: (commit) => {
            try {
              if (!commit.committerDate) return false;
              const date = new Date(commit.committerDate);
              if (Number.isNaN(date.getTime())) return false;
              return commit;
            } catch (e) {
              return false;
            }
          }
        }
      }
    ],


    [
      "@semantic-release/exec",
      {
        prepareCmd:
          "jq '.version = \"${nextRelease.version}\"' custom_components/smhi_alerts/manifest.json > manifest.tmp && mv manifest.tmp custom_components/smhi_alerts/manifest.json && cd custom_components && zip -r smhi_alerts.zip smhi_alerts"
      }
    ],

    [
      "@semantic-release/github",
      {
        draftRelease: true,
        assets: [
          {
            path: "custom_components/smhi_alerts.zip",
            label: "smhi_alerts.zip"
          }
        ]
      }
    ]
  ]
};