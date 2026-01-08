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
        presetConfig: {
          types: [
            { "type": "feat", "section": "✨ New features" },
            { "type": "fix", "section": "🐛 Bug fixes" },
            { "type": "docs", "section": "📚 Documentation" },
            { "type": "refactor", "section": "🧹 Refactoring" },
            { "type": "chore", "section": "🔧 Maintenance" },
            { "type": "*", "section": "📦 Other changes" }
          ]
        },
        writerOpts: {
          mainTemplate,
          groupBy: "type",
          commitGroupsSort: "title",
          commitsSort: ["scope", "subject"],
          transform: (commit) => {
            if (!commit.type) {
              commit.type = "other";
            } else {
              commit.type = commit.type.toLowerCase();
            }

            const rawDate =
              commit.committerDate ||
              commit.authorDate ||
              commit.commit?.committer?.date ||
              commit.commit?.author?.date;

            const date = new Date(rawDate);
            commit.committerDate = Number.isNaN(date.getTime())
              ? new Date().toISOString()
              : date.toISOString();

            return commit;
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