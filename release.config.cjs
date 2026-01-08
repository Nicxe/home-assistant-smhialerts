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

          // 🔒 KRITISKT: skyddar mot trasiga commits
          transform: (commit) => {
            delete commit.committerDate;
            delete commit.commitDate;
            return commit;
          }
        }
      }
    ],

    [
      "@semantic-release/exec",
      {
        prepareCmd:
          "jq '.version = \"${nextRelease.version}\"' custom_components/<integration_name>/manifest.json > manifest.tmp && " +
          "mv manifest.tmp custom_components/<integration_name>/manifest.json && " +
          "cd custom_components && zip -r <integration_name>.zip <integration_name>"
      }
    ],

    [
      "@semantic-release/github",
      {
        draft: true,
        assets: [
          {
            path: "custom_components/<integration_name>.zip",
            label: "<integration_name>.zip"
          }
        ]
      }
    ]
  ]
};