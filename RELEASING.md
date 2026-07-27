# Releasing Golf Sim Analytics

The path from "I changed the app" to "users are running it". Binaries never go
through git — `dist/` and `installer/Output/` are gitignored — they ship as
GitHub Release assets, and the website's download button follows the latest
release automatically.

## Phase 1 — Code (every change)

```powershell
cd C:\dev\golf-sim-analytics
```

1. Make the change.
2. Run the tests: `python -m pytest -q`. Green before anything ships.
3. Bump `APP_VERSION` in `config.py` — patch (`1.2.0 -> 1.2.1`) for fixes,
   minor (`-> 1.3.0`) for features. This stamps the Settings footer (how you
   verify which build is running) and every contribution manifest.
4. Branch, commit, PR, merge to `main`.
5. Sync: `git checkout main` then `git pull`.

## Phase 2 — Build the installer

6. Close the app if it's running (an open exe locks `dist\`).
7. `.\build_installer.bat` — builds the exe (PyInstaller) and compiles the
   installer (Inno Setup) in one go. Output:
   `installer\Output\GolfSimAnalytics-Setup.exe`.
   - Missing Inno Setup? `winget install JRSoftware.InnoSetup`, re-run.

## Phase 3 — Publish

8. ```powershell
   gh release create vX.Y.Z "installer\Output\GolfSimAnalytics-Setup.exe" --title "vX.Y.Z" --notes "What changed"
   ```

Three rules:

- **Never mark it pre-release.** The website's direct-download link only
  follows full releases; a pre-release leaves the button serving the old
  version. The app's own update check reads `/releases/latest` for the same
  reason — a pre-release is invisible to both.
- **Never rename the asset.** The site resolves
  `releases/latest/download/GolfSimAnalytics-Setup.exe` by exact name
  (`INSTALLER_ASSET_NAME` in the website repo's `src/consts.ts`, matching
  `OutputBaseFilename` in `installer/GolfSimAnalytics.iss`, and
  `config.LATEST_DOWNLOAD_URL` for the app's Download button).
- **Tag as `vX.Y.Z`, and bump `config.APP_VERSION` to match.** The update
  notice compares the two: a tag whose number isn't higher than the shipped
  `APP_VERSION` shows nobody anything (`version_check.is_newer`). Forgetting
  the `APP_VERSION` bump is the quiet failure — the release goes out, and
  every existing install keeps believing it's current.

Publishing the release IS the site update — the download button points at the
new installer immediately, no site deploy involved. It's also what tells
existing installs there's something to update to; there's no separate step.

## Phase 4 — Only when the contribution schema or Worker changed

```powershell
cd C:\dev\opengolflab-data\worker
wrangler deploy
```

Needed only when `worker/src/index.js` changed or the app now sends a newer
`schema_version` than the deployed Worker accepts. Pure app/UI changes skip
this.

## Verify

- Run the new installer, open Settings: the footer shows the new version.
- opengolflab.com/download now serves the new Setup.

## What never needs a manual step

- **Website** — CI builds and deploys on every push to `main`
  (`.github/workflows/deploy-workers.yml` in the website repo).
- **Community data** — contributions auto-aggregate and publish
  (`.github/workflows/aggregate.yml` in the data repo).
- **Pushing binaries** — never. Releases carry them; git carries source.
