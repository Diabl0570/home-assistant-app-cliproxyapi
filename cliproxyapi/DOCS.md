# CLIProxyAPI Home Assistant app

## Options

| Option | Meaning |
| --- | --- |
| `api_keys` | Nonempty list of client API keys, used as Bearer credentials. These are separate from provider keys. |
| `management_password` | A separate random password with at least 24 characters and no leading or trailing spaces for the management panel/API. |
| `logging` | Debug logging to the Home Assistant app log; false by default. Request/response logging is disabled. Debug logs may contain provider details. |
| `routing_strategy` | How new conversations spread over your accounts: `round-robin` (default) or `fill-first`. See [Routing](#routing). |
| `session_affinity` | Keep one conversation on the same account; true by default. |
| `session_affinity_ttl` | How long an idle conversation stays bound to its account, such as `1h` (default), `30m` or `2h30m`. |
| `retry_other_accounts` | Retry a failed request on your other accounts; true by default. Off only stops that retry within the same request; see [Routing](#routing). |
| `blocked_models` | Exact model IDs, without a credential prefix, that the proxy neither lists nor serves; `gpt-6-sol` and `gpt-5.6-sol` by default, plus Devin's `devin/gpt-6-sol` and `devin/gpt-5-6-sol`. An empty list blocks nothing. See [Blocked models](#blocked-models) for the limits. |
| `diagnostics_keys` | Optional keys for the read-only [diagnostics](#diagnostics) endpoint on port 18318; empty (off) by default. Each needs at least 24 characters without leading or trailing spaces and must differ from `api_keys` and `management_password`, also when those have surrounding spaces. |

Generate distinct random credentials, for example with `openssl rand -hex 32`. Save them in app configuration before starting. The wrapper rejects empty client keys and short management passwords without printing the secret values.

## CPA Manager Plus

The app bundles [CPA Manager Plus](https://github.com/seakee/CPA-Manager-Plus) (Full Mode Manager Server), an extended management panel with persistent request history, usage and cost analytics, quota and account health. It runs next to the proxy in the same app and is connected to it automatically.

1. In Home Assistant open **Settings → Apps → CLIProxyAPI** and select **Open Web UI**. This opens `http://HOME_ASSISTANT_IP:18317/management.html`.
2. Log in with your `management_password`. It is also the CPA Manager Plus admin key; changing the option changes both on the next start.
3. The CPA connection is preconfigured: the manager reaches the proxy internally at `http://127.0.0.1:8317` with the same password. Do not change the CPA address or key in its settings; the app sets them on every start.

Request history, settings and the encryption key `data.key` live in `/data/cpa-manager-plus/` and are part of Home Assistant app backups. Monitoring needs CLIProxyAPI usage statistics; the app turns `usage-statistics-enabled` on unless you have switched it off in a panel. CPA Manager Plus's own update check is disabled because the app pins it; see [Updating CPA Manager Plus](#updating-cpa-manager-plus).

The stock CLIProxyAPI panel is unchanged and still available at `http://HOME_ASSISTANT_IP:8317/management.html`. Both panels manage the same proxy configuration.

## Diagnostics

An optional, read-only endpoint lists recent failed or interrupted requests, so you can match a client's model-connection error or a provider overload to what the proxy saw. It is off until you set at least one `diagnostics_keys` value; give each tool its own random key, for example from `openssl rand -hex 32`, then restart the app.

```sh
curl -H 'Authorization: Bearer <diagnostics-key>' 'http://HOME_ASSISTANT_IP:18318/diagnostics/failures?hours=24&limit=50'
```

`GET /diagnostics/failures` is the only request it answers. `hours` (1–168, default 24) sets how far back to look and `limit` (1–200, default 50) caps how many failures, newest first, are returned; `truncated` is true when there were more. Each failure has only these fields; a field is `null` when it is unknown:

| Field | Meaning |
| --- | --- |
| `time` | When the request was recorded, in UTC. |
| `model` | The model the request named. |
| `provider` | The provider of the account that served it, such as `codex`. |
| `account` | The account's configured label, or `acct-` and a short stable hash when the label is missing, looks like an email or key, or is the label CLIProxyAPI gives every API key of a provider, such as `codex-apikey`. |
| `status` | The upstream HTTP status. |
| `error` | The class of `status`: `rate_limited`, `overloaded`, `unavailable`, `timeout`, `unauthorized`, `forbidden`, `bad_request`, `not_found`, `server_error`, `client_error` or `interrupted` (`status` is `null`, 0 or 499). |
| `message` | A fixed description of `error`, such as `Provider overloaded`. It is never the provider's own error message, which can quote the prompt. |
| `streamed` | Whether the client asked for a streamed response. |
| `output_tokens` | Output tokens counted before the failure. |
| `duration_ms` | How long the request took. |
| `request_id` | The proxy's request ID. |

It never returns prompts, responses, provider error messages, headers, client or provider keys, OAuth or auth-file contents, emails, client addresses or configuration, and it cannot change anything. A diagnostics key is not accepted by the API or either management panel, and the client keys and management password are not accepted by diagnostics.

Diagnostics is a small separate process in the app. It reads the failed requests from CPA Manager Plus's request history, the query behind its Monitoring page, using the management password internally, and passes on only the fields above. It needs the history CPA Manager Plus keeps, so failures before the history started, or while usage statistics are switched off, are not listed. Diagnostics does not log requests.

When CPA Manager Plus is not reachable, or its answer no longer matches what diagnostics asked for and expects (the fields and types it reads, only failures, only the requested hours and at most `limit` of them), the endpoint answers `503` with `{"status": "unavailable", "reason": ...}` instead of guessing; the reason is `manager_unreachable`, `manager_unauthorized`, `manager_error`, `interface_incompatible` or `busy`. The proxy and CPA Manager Plus keep running whether diagnostics works, fails to start or stops, and invalid `diagnostics_keys` only turn diagnostics off, with a note in the app log.

## Provider setup

Open CPA Manager Plus (**Web UI**) or the stock panel at `http://HOME_ASSISTANT_IP:8317/management.html` and connect using the management password. The stock panel downloads on first access, so outbound GitHub access is needed. Periodic stock panel updates are disabled for predictability. The upstream stock panel is independent of the pinned server release; its initial download is not checksum-pinned. CPA Manager Plus is part of the app image and needs no download.

Add a provider API key in the management panel, or import a supported CLIProxyAPI OAuth auth JSON via its auth-file upload. Auth import avoids callback networking and is the easiest fallback. See [upstream documentation](https://github.com/router-for-me/CLIProxyAPI) for supported providers and account login requirements.

OAuth login may redirect your browser to `localhost`, meaning the computer with your browser rather than Home Assistant. If the panel offers a callback-URL field, paste the full final redirect URL there, even if the page failed to load. Otherwise use upstream auth-file import, or an SSH local-port tunnel to the relevant callback port. This app does not configure SSH or tunnels. Optional callback ports in the Network section are disabled by default; exposing a callback port on Home Assistant alone does not resolve a browser's localhost redirect. Do not enable them unless your specific login method needs them.

## Persistence and ownership

The app's private `/data` holds `cliproxy.yaml`, `auths/` and `cpa-manager-plus/`. Provider keys, provider settings and OAuth auth files survive restarts and app updates. They are included in Home Assistant app backups; protect your backups. Existing YAML written by the management panel is read safely on startup, merged, and serialized as JSON (valid YAML).

App options control these fields on every startup: config version, server host/port/TLS enable, client access keys, management remote access/password/panel settings, OAuth auth directory, debug/stdout/request logging, the routing fields listed under [Routing](#routing), the model exclusions listed under [Blocked models](#blocked-models), and the CPA Manager Plus admin key and proxy connection. Changes to those fields through the management panel are overwritten on restart. Other settings, including provider configuration, are retained. The config file has mode 0600, auth directory 0700, existing auth files 0600, and the server inherits a private umask.

## Routing

The routing options decide which of your provider accounts serves a request. The defaults keep one conversation on one account, so the provider's prompt cache can be reused, spread new conversations over all accounts, and switch accounts automatically when one runs out of quota or fails.

To change them, open the app in Home Assistant, go to the **Configuration** tab, edit the options and select **Save**, then restart the app. An existing install that predates these options gets the defaults on its next start.

The app writes the options into the proxy's persistent config, `/data/cliproxy.yaml`, on every start:

| Option | Default | Routing field in the proxy config |
| --- | --- | --- |
| `routing_strategy` | `round-robin` | `strategy` |
| `session_affinity` | `true` | `session-affinity` |
| `session_affinity_ttl` | `1h` | `session-affinity-ttl` |
| `retry_other_accounts` | `true` | `retry.request-retry` (3, or 0 when off), `retry.max-retry-credentials` (0 = try every account, or 1 when off) |

- `routing_strategy`: `round-robin` rotates over the accounts, and `fill-first` uses the first account until it is unavailable.
- `session_affinity_ttl`: a binding expires after this much idle time; each request in the conversation renews it. Use hours, minutes and seconds in that order, such as `1h`, `45m` or `1h30m`.
- `retry_other_accounts`: when on, a request that fails on one account is retried on your other accounts within that same request. When off, a failed request returns the error without trying another account. Turning it off only stops retrying another account within the same request: CLIProxyAPI 8.0.10 still moves a conversation to another account after a credential failure such as a 429, so the conversation's next request can go to a different account. Retry overrides set on an individual provider or credential still take precedence.
- If session affinity is on and the bound account runs out of quota or fails, CLIProxyAPI moves the conversation to another account automatically.
- Bindings are kept in memory only and are lost on restart.

Other routing fields, such as `session-affinity-subagents` (subagents with a parent session stay on the parent's account; true by default), `retry.max-retry-interval` and the `cooldown` settings, are not app options. The app leaves them as they are in `/data/cliproxy.yaml`, so they survive restarts and app updates; set them in the management panel or with the management API.

**Precedence:** the app options are applied at every start. A change to a field in the table above made in the management panel or management API applies live, but lasts only until the next restart, when the app options overwrite it. To make a lasting change, change the app option.

To inspect or briefly test routing without a restart, use the management API with the management password:

```sh
curl -X PATCH -H 'Authorization: Bearer <management-key>' -H 'Content-Type: application/json' \
  -d '{"strategy":"round-robin","session-affinity":true,"session-affinity-ttl":"1h","session-affinity-subagents":true}' \
  http://<proxy-host>:8317/v8/management/config/routing
```

PATCH keeps routing fields you leave out; PUT replaces the whole routing section. The change applies live without a restart, and every routing change resets the in-memory affinity bindings. Read the routing settings back with `GET /v8/management/config/routing` only. Do not use a whole-config read (`/v8/management/config` or `/v8/management/config.yaml`) for this: it is not secret-redacted and includes client API keys and the management password.

## Blocked models

`blocked_models` lists the model IDs the proxy hides and refuses. By default it blocks GPT-6 Sol and GPT-5.6 Sol: `gpt-6-sol` and `gpt-5.6-sol` from Codex, and `devin/gpt-6-sol` and `devin/gpt-5-6-sol` from Devin. Of the Sol models, only `gpt-6.1-sol` stays available. A blocked model is missing from `/v1/models`, also under any credential prefix. A request naming it gets `400 model_not_found` without reaching any account. Other models keep working. The paths listed at the end of this section are not covered.

To change the list, open the app in Home Assistant, go to the **Configuration** tab, add or remove model IDs under `blocked_models`, select **Save**, then restart the app. Each entry is one exact model ID, compared case-insensitively. `*` is not allowed. Remove every entry to block nothing.

Use the model ID without a credential routing prefix. A credential with a prefix such as `work` lists its models as `work/gpt-6-sol`. The entry `gpt-6-sol` also blocks `work/gpt-6-sol` and every other prefixed copy, while an entry `work/gpt-6-sol` blocks nothing. Devin is the exception: `devin/` is part of Devin's own model IDs, not a routing prefix, so Devin models are listed as `devin/gpt-6-sol`. An existing install that predates this option gets the default list on its next start.

The app owns these exclusion fields in `/data/cliproxy.yaml` and rewrites them from the option on every start:

- `oauth.excluded-models`: one list per OAuth provider, for `codex`, `devin` and the other built-in providers, plus any provider already in that section. It covers every OAuth account and imported auth file. A legacy `oauth-excluded-models` section is removed.
- `excluded-models` on each provider API key group under `api-keys`, or on each entry of a legacy list such as `codex-api-key`. It covers API key credentials.
- `excluded-models` on a key inside a group. A key's own list would replace its group's, so the app removes it and the key uses its group's list. A key that sets its own `models` gets its own list instead.
- On an API key, CLIProxyAPI matches the name clients use: a model's alias, or else its name. In the `models` of a group, key or legacy entry, the app also excludes, for that credential, each such name that a request can send to a blocked model. For example, `{name: gpt-6-sol, alias: legacy-sol}` hides `legacy-sol`, and a model named `gpt-6-sol(high)` is hidden like `gpt-6-sol`.
- CLIProxyAPI sends an alias to the first entry that matches it exactly or without its thinking suffix, and serves a request for `sol(high)` through the name `sol`. So `{name: gpt-6-sol, alias: sol(high)}` also hides `sol`, wherever it appears in the list. When the first entry for `sol` is `{name: gpt-6.1-sol, alias: sol}`, a later `{name: gpt-6-sol, alias: sol}` never receives requests, and `sol` stays available.

Exclusions you set yourself in these fields, in the YAML or in the management panel, are replaced with the option list at the next start. An empty list removes them. A change to these fields made in the management panel applies live, but only until the next restart.

A new OAuth account is covered as soon as it is added, because its provider's list already exists. A provider API key added in the management panel gets the exclusions at the next restart. Restart the app after adding one.

CLIProxyAPI 8.0.10 has no exclusion setting for these paths, so the block cannot cover them:

- An `openai-compatibility` provider serves the models you list for it. Do not list a blocked model there.
- An OAuth model alias (`oauth.model-alias`) you name after a blocked model, such as `{name: gpt-6.1-sol, alias: gpt-6-sol}`, appears in `/v1/models` under that name. It serves the model it aliases (here GPT-6.1 Sol), not the blocked one.
- An OAuth model alias whose target is a blocked model, in `oauth.model-alias` or in an account's auth file, can still send requests to the blocked model. For example, `{name: gpt-6-sol, alias: gpt-6.1-sol}` sends requests for `gpt-6.1-sol` to GPT-6 Sol. Remove every alias that targets a blocked model.
- Models added by a CLIProxyAPI plugin are not filtered.

## Network

API and the stock management panel share TCP 8317; CPA Manager Plus uses TCP 18317; diagnostics uses TCP 18318 and listens only when `diagnostics_keys` is set. All default mappings are LAN-accessible HTTP, reachable wherever your Home Assistant host is, such as over a VPN you already route to it; the API requires a client key, both panels require the management password and diagnostics requires a diagnostics key. Use only on a trusted local network. Do not forward these ports from your router. An HTTPS reverse proxy is needed for access outside a trusted network. This app has no Home Assistant ingress or Supervisor API permissions. A running proxy does not automatically integrate it into Home Assistant's Assist: your chosen client/integration must support a custom OpenAI-compatible base URL.

## Troubleshooting

- Startup stops: supply nonempty client keys and a separate 24+ character management password without leading or trailing spaces, a `session_affinity_ttl` such as `1h` or `30m`, and only exact model IDs without `*` in `blocked_models`.
- Startup stops with "admin key could not be reset": CPA Manager Plus could not take the current `management_password`, so the app refuses to start rather than keep the previous password valid. Restart the app to retry.
- Models list empty: configure/import at least one provider first.
- UI unavailable: check app logs and port mapping; the stock panel also needs outbound access for its initial download.
- CPA Manager Plus login fails: use the current `management_password` and restart the app after changing it.
- CPA Manager Plus Monitoring is empty: send a new request through the proxy and check that usage statistics are enabled in the panel.
- Diagnostics refuses connections: set `diagnostics_keys` and restart; the app log says when invalid keys turned it off. `401` means the key is not one of `diagnostics_keys`. `503` with `interface_incompatible` means the pinned CPA Manager Plus no longer offers the query diagnostics uses or answers it differently; the proxy is unaffected, and diagnostics stays unavailable until an app update adapts it.
- Image pull denied: maintainer must publish the corresponding image version and make its GHCR package public.
- On-device acceptance: verify startup, Web UI, provider login, authenticated request, backup and restart on your HAOS system before relying on it.

## Updating CPA Manager Plus

CPA Manager Plus is pinned to an exact upstream release and its official SHA-256 in `cliproxyapi/manager-plus.json`, like the CLIProxyAPI binary in `cliproxyapi/updater.json`. You do not update it from inside the panel.

- Automatic: the daily **Check upstream updates** workflow runs `scripts/update_manager_plus.py`. When a newer stable v1 release appears, it opens a pull request that changes the pin, the checksum, the app version suffix (for example `8.0.4-5` → `8.0.4-6`) and the changelog, then starts the build for that branch. Merging it publishes a new app version; Home Assistant then offers **Update**.
- Manual: run the workflow with **Run workflow** in GitHub Actions, or run `python3 scripts/update_manager_plus.py` locally and open a pull request with the result.
- Refused for manual review: prereleases, a new major version, and releases whose upstream `release-info.json` marks them breaking, needing migration, or needing a newer CLIProxyAPI than the pinned one. To take such a release, review its upgrade notes, then edit `version`, `asset` and `sha256` in `cliproxyapi/manager-plus.json` from the release's `checksums.txt`, and bump the app version and changelog.

Back up the app before updating; the manager database migrates forward on start.

## Updates and diagnostics compatibility

Upstream updates stay plain version and checksum bumps of the official CLIProxyAPI and CPA Manager Plus releases. The app never patches or rebuilds either upstream; diagnostics is a separate process that only reads CPA Manager Plus's existing request-history query, so the update workflow needs no changes for it.

Every build, including the build the update workflow starts for its pull request, runs a separate **diagnostics-compatibility** check. It builds the image with the pinned releases and sends a request through the real proxy to a fake provider inside the container, using only synthetic credentials and no real provider accounts. It then checks that diagnostics accepts the real CPA Manager Plus answer and lists the failure with only the allowed fields, the fixed message and no secrets or provider error text; that it answers `interface_incompatible` when the query is missing; and that stopping diagnostics leaves the proxy running.

If an upstream release changes that query or the fields and types it returns, only this check fails: the image build, smoke test and publishing do not depend on it. You can merge the update anyway, and diagnostics then answers `unavailable` while the proxy works normally, or adapt diagnostics in the same pull request first.
