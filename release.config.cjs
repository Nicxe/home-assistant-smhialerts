const config = require("@nicxe/semantic-release-config")({
  componentDir: "custom_components/smhi_alerts",
  manifestPath: "custom_components/smhi_alerts/manifest.json",
  projectName: "SMHI Weather Warnings & Alerts",
  repoSlug: "Nicxe/home-assistant-smhialerts"
}
);

const githubPlugin = config.plugins.find(
  (plugin) => Array.isArray(plugin) && plugin[0] === "@semantic-release/github"
);

if (githubPlugin?.[1]) {
  githubPlugin[1].successCommentCondition = false;
}

module.exports = config;
