const fs = require("fs");
const path = require("path");
const conventionalCommits = require("conventional-changelog-conventionalcommits");
const defaultWriterOpts = conventionalCommits.writerOpts || {};

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
          ...defaultWriterOpts,
          mainTemplate,
          groupBy: "type",
          commitGroupsSort: "title",
          commitsSort: ["scope", "subject"],
          transform: (commit, context) => {
            // Ensure unknown/missing types end up in the "Other changes" section
            if (!commit.type) {
              commit.type = "*";
            }

            // Normalize type for matching against presetConfig
            if (typeof commit.type === "string" && commit.type !== "*") {
              commit.type = commit.type.toLowerCase();
            }

            // Run the preset's default transform first so type->section mapping works
            const transformed = defaultWriterOpts.transform
              ? defaultWriterOpts.transform(commit, context)
              : commit;

            // Preset transform can filter commits by returning null
            if (!transformed) {
              return transformed;
            }

            // Make sure we always have a subject, otherwise skip the commit
            transformed.subject =
              transformed.subject || commit.subject || commit.header || "";
            if (!transformed.subject.trim()) {
              return null;
            }

            // Sanitize/normalize dates to avoid "RangeError: Invalid time value"
            const rawDate =
              commit.committerDate ||
              commit.authorDate ||
              transformed.committerDate ||
              transformed.authorDate ||
              commit.commit?.committer?.date ||
              commit.commit?.author?.date;

            const date = new Date(rawDate);
            transformed.committerDate = Number.isNaN(date.getTime())
              ? new Date().toISOString()
              : date.toISOString();

            return transformed;
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