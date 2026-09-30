# CLIProxyAPI Home Assistant app

## Options

| Option | Meaning |
| --- | --- |
| `api_keys` | Nonempty list of client API keys, used as Bearer credentials. These are separate from provider keys. |
| `management_password` | A separate random password with at least 24 characters for the management panel/API. |
| `logging` | Debug logging to the Home Assistant app log; false by default. Request/response logging is disabled. Debug logs may contain provider details. |

Generate distinct random credentials, for example with `openssl rand -hex 32`. Save them in app configuration before starting. The wrapper rejects empty client keys and short management passwords without printing the secret values.

## Provider setup

Open `http://HOME_ASSISTANT_IP:8317/management.html` (or **Web UI**) and connect using the management password. The panel downloads on first access, so outbound GitHub access is needed. Periodic panel updates are disabled for predictability. The upstream panel is independent of the pinned server release; the initial panel download is not checksum-pinned.

Add a provider API key in the management panel, or import a supported CLIProxyAPI OAuth auth JSON via its auth-file upload. Auth import avoids callback networking and is the easiest fallback. See [upstream documentation](https://github.com/router-for-me/CLIProxyAPI) for supported providers and account login requirements.

OAuth login may redirect your browser to `localhost`, meaning the computer with your browser rather than Home Assistant. If the panel offers a callback-URL field, paste the full final redirect URL there, even if the page failed to load. Otherwise use upstream auth-file import, or an SSH local-port tunnel to the relevant callback port. This app does not configure SSH or tunnels. Optional callback ports in the Network section are disabled by default; exposing a callback port on Home Assistant alone does not resolve a browser's localhost redirect. Do not enable them unless your specific login method needs them.

## Persistence and ownership

The app's private `/data` holds `cliproxy.yaml` and `auths/`. Provider keys, provider settings and OAuth auth files survive restarts and app updates. They are included in Home Assistant app backups; protect your backups. Existing YAML written by the management panel is read safely on startup, merged, and serialized as JSON (valid YAML).

App options control these fields on every startup: config version, server host/port/TLS enable, client access keys, management remote access/password/panel settings, OAuth auth directory, debug/stdout/request logging. Changes to those fields through the management panel are overwritten on restart. Other settings, including provider configuration, are retained. The config file has mode 0600, auth directory 0700, existing auth files 0600, and the server inherits a private umask.

## Network

API and management share TCP 8317; default mapping is LAN-accessible HTTP. Use only on a trusted local network. Do not forward this port from your router. An HTTPS reverse proxy is needed for access outside a trusted network. This app has no Home Assistant ingress or Supervisor API permissions. A running proxy does not automatically integrate it into Home Assistant's Assist: your chosen client/integration must support a custom OpenAI-compatible base URL.

## Troubleshooting

- Startup stops: supply nonempty client keys and a separate 24+ character management password.
- Models list empty: configure/import at least one provider first.
- UI unavailable: check app logs, port mapping and outbound access for the initial panel download.
- Image pull denied: maintainer must publish the corresponding image version and make its GHCR package public.
- On-device acceptance: verify startup, Web UI, provider login, authenticated request, backup and restart on your HAOS system before relying on it.
