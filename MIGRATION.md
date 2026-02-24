# Migration Guide

## Who is this for?
This guide is for users who previously installed the alert card from `Nicxe/home-assistant-smhialert-card`.

## What changed?
The alert card is now bundled directly in `Nicxe/home-assistant-smhialerts` and managed by the integration.
The integration syncs the bundled card to `/config/www/smhi-alert-card.js`, syncs required sidecar assets, and keeps the Lovelace resource at `/local/smhi-alert-card.js?v=...` updated to reduce stale browser cache issues.

## What you need to do
1. Install or update the integration from `Nicxe/home-assistant-smhialerts` in HACS as type **Integration**.
2. Remove `Nicxe/home-assistant-smhialert-card` from HACS if it is still installed.
3. Keep existing Lovelace cards as-is. The integration keeps `/local/smhi-alert-card.js?v=...` updated automatically.
4. Restart Home Assistant once.
5. Hard refresh the browser once (Ctrl/Cmd + Shift + R).

## Integration users
No change is needed to the integration install flow. Continue using HACS for the integration package.

## Release and rollout process
For maintainers, rollout runs through `dev -> beta -> main`.
After merge to `dev`, there is a required manual beta validation pause before promotion to `main`.
