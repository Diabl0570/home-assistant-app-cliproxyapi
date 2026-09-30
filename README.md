# CLIProxyAPI for Home Assistant app (add-on)

Run [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) on your Home Assistant OS device. Community app for **amd64**, including bare-metal x86-64 systems; not an official Home Assistant or CLIProxyAPI project.

The public repository and container image are published under `Diabl0570`. Use the `stable` branch below to install releases that passed the container build and smoke test.

## Install

1. In Home Assistant open **Settings → Apps → App store → ⋮ → Repositories** (older versions call these Add-ons).
2. Add `https://github.com/Diabl0570/home-assistant-app-cliproxyapi#stable`.
3. Install **CLIProxyAPI**. Set `api_keys` to one or more random client keys and `management_password` to a different random password of at least 24 characters. Defaults intentionally cannot start.
4. Start the app and enable **Start on boot**. Open **Web UI** to manage providers.
5. Use `http://HOME_ASSISTANT_IP:8317/v1` and a client API key in compatible clients.

[English documentation](cliproxyapi/DOCS.md) · [Nederlandse snelstart](cliproxyapi/QUICKSTART.nl.md)

## Updates

A daily workflow proposes stable CLIProxyAPI v8 updates in a pull request. Release asset, checksum, app version and changelog change together. The updater explicitly dispatches the build workflow for its PR branch, because GitHub suppresses ordinary PR triggers created with `GITHUB_TOKEN`. Review the successful build before merging. New major upstream versions require a manual compatibility review. A successful main build publishes the versioned amd64 image to GHCR. Only after an anonymous image-pull check passes does the workflow advance the `stable` installation branch. Home Assistant detects the changed app version and offers **Update** after refreshing the store; users do not have to rebuild upstream themselves.

Inspired by the app structure and update approach of [alexbelgium/hassio-addons](https://github.com/alexbelgium/hassio-addons). Implementation is a small standalone wrapper, without copying its scripts.

## Maintainer setup

Publish this directory as a public repository under your personal account, then enable GitHub Actions. In repository Settings → Actions → General enable **Allow GitHub Actions to create and approve pull requests**. After the first successful main build, make the GHCR package **public** in package settings; public repository visibility does not guarantee public package visibility. Rerun the main build after making the package public: its anonymous pull check gates creation of the `stable` installation branch. The Home Assistant install requires anonymous image pull access.

Example publication from this directory, after creating a main commit:

```sh
gh repo create Diabl0570/home-assistant-app-cliproxyapi --public --source=. --remote=origin --push
```

Published image tags are immutable: bump the app version wrapper suffix (for example `8.0.4-2`) for changes after a version is published. A rerun of the same commit can reuse its existing image, including after changing package visibility.

The build uses Debian glibc, upstream release 8.0.4 and its official SHA-256. `cliproxyapi/updater.json` is the authoritative upstream pin. Local verification:

```sh
python3 -m pip install PyYAML==6.0.2
python3 -m unittest discover -s cliproxyapi/tests -v
docker build --build-arg BUILD_ARCH=amd64 -t ha-cliproxy-test cliproxyapi
python3 scripts/smoke.py
```

The smoke test uses no provider accounts. Actual Home Assistant installation and provider login still require testing on a Home Assistant device.

MIT license applies to this wrapper. The container includes the upstream release LICENSE; upstream and the separately downloaded management panel retain their own licensing.
