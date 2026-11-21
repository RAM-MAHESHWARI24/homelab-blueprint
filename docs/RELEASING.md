# Releasing

How a homelab-blueprint release is cut, and how each module reaches its own repository.

## The model

`homelab-blueprint` is the only place code is written. Four module folders are also published as their own repositories, so people who already run a homelab can use one piece without the installer:

| Folder | Published repository |
| :--- | :--- |
| `apps/control-hub/` | [control-hub](https://github.com/RAM-MAHESHWARI24/control-hub) |
| `apps/mediaserver/` | [homelab-mediaserver](https://github.com/RAM-MAHESHWARI24/homelab-mediaserver) |
| `apps/immich-face-xmp-exporter/` | [noodle-gallery-tools](https://github.com/RAM-MAHESHWARI24/noodle-gallery-tools) |
| `apps/tv-autoupdater/` | [tv-autoupdater](https://github.com/RAM-MAHESHWARI24/tv-autoupdater) |

`apps/noodle-gallery/` stays in the monorepo only. Each folder's `module.json` says whether and where it is published.

**The published repositories are read-only mirrors.** Every release replaces their `main` branch with the monorepo's history of that folder. Anything committed directly to a module repository is lost on the next release, so contributions there are re-applied in the monorepo.

## What keeps a module publishable

A module must work when its folder is copied out alone. Two CI checks enforce that on every pull request:

- **Module contract** ([`testing/test_module_contract.py`](../testing/test_module_contract.py)):
  - every published module has a README, LICENSE, an example config, `module.json`, an executable `install.sh` and `ci.sh`, and its own `.github/workflows/ci.yml`;
  - no file refers to another module's folder or to a path outside its own, and no README links outside it.
- **Split simulation:** a CI job copies each published module's tracked files out of the repository and runs its `ci.sh` there, with ShellCheck and Docker available. The module repository's own workflow runs the same `ci.sh`, so both places test the same thing.

A module's `.github/workflows/ci.yml` does nothing inside the monorepo, because GitHub only runs workflows at a repository's root. It becomes active once the folder is published.

## Cutting a release

1. Merge everything for the release into `develop`, then merge `develop` into `main`. Both branches are protected: changes arrive through pull requests with green CI.
2. In that pull request, set the new version everywhere it is reported, and date it in the changelog:

   | File | What to change |
   | :--- | :--- |
   | [`CHANGELOG.md`](../CHANGELOG.md) | Rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` and add a new empty `## [Unreleased]` above it |
   | [`setup/installer/deployer.py`](../setup/installer/deployer.py) | `BLUEPRINT_VERSION` |
   | [`setup/server.py`](../setup/server.py) | the `version` in the wizard's `/api/health` reply |
   | [`apps/control-hub/server.py`](../apps/control-hub/server.py) | the `version` in the Control Hub's `/api/health` reply |
   | [`apps/control-hub/docs/openapi.yaml`](../apps/control-hub/docs/openapi.yaml) | `info.version` and the health example |
   | [`apps/control-hub/README.md`](../apps/control-hub/README.md) | the release badge |

   [`testing/test_version_consistency.py`](../testing/test_version_consistency.py) fails in CI, and in the pre-push hook, while the four version strings and the newest dated changelog heading disagree. That check exists because v2.1.0 shipped reporting 2.0.0.
3. Tag `main` and push the tag:

   ```bash
   git fetch origin
   git tag -a v2.1.1 origin/main -m "v2.1.1"
   git push origin v2.1.1
   ```

Pushing a `v*` tag starts two workflows:

- [`release.yml`](../.github/workflows/release.yml) publishes the GitHub release with source archives.
- [`split.yml`](../.github/workflows/split.yml) publishes the modules. For each module with `"publish": true` it runs `git subtree split --prefix apps/<folder>`, force-pushes the result to the module repository's `main`, and pushes the same tag there.

`bootstrap.sh` installs the latest tag by default, so a new tag reaches new installs straight away.

## Trying the split without releasing

Run **Split modules into their repositories** from the Actions tab, choose a branch or tag, and leave **dry run** ticked. It builds each module's history and lists its files, but pushes nothing.

## Secrets and keys

Each module repository has a deploy key with write access. Its private half is stored in this repository as an Actions secret, named in `module.json` under `split_secret`:

| Secret | Repository |
| :--- | :--- |
| `SPLIT_KEY_CONTROL_HUB` | control-hub |
| `SPLIT_KEY_MEDIASERVER` | homelab-mediaserver |
| `SPLIT_KEY_NOODLE_TOOLS` | noodle-gallery-tools |
| `SPLIT_KEY_TV_AUTOUPDATER` | tv-autoupdater |

To replace a key, create a new one, add its public half as a deploy key with write access on the module repository, and update the secret:

```bash
ssh-keygen -t ed25519 -N "" -f /tmp/split-key -C "homelab-blueprint split -> control-hub"
gh repo deploy-key add /tmp/split-key.pub -R RAM-MAHESHWARI24/control-hub --allow-write --title "homelab-blueprint split release"
gh secret set SPLIT_KEY_CONTROL_HUB -R RAM-MAHESHWARI24/homelab-blueprint < /tmp/split-key
rm /tmp/split-key /tmp/split-key.pub
```

Then delete the old deploy key on the module repository.

## Publishing a new module

1. Give the folder the standalone files the contract test asks for, and a `module.json` with `"publish": true`, the repository and a new `SPLIT_KEY_*` secret name.
2. Create the empty repository and its deploy key and secret as above.
3. Add the folder to the `split-simulation` matrix in [`ci.yml`](../.github/workflows/ci.yml).
4. Run the split workflow as a dry run, then release.

## If a split fails

- **"Secret ... is not set":** the secret named in `module.json` is missing. Add it as above.
- **Permission denied on push:** the deploy key is missing on the module repository, or it was added without write access.
- **One module failed, others pushed:** each module is a separate job. Fix the cause and re-run only the failed job, or run the workflow by hand for the same tag with dry run unticked.
