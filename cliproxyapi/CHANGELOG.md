# 8.0.10-4

- Update CPA Manager Plus to 1.14.5; upstream checksum pinned.

# 8.0.10-3

- Add the `retry_before_output` app option using CLIProxyAPI's native retry settings. See [Retries before output](DOCS.md#retries-before-output) for defaults, fixed class waits, limits and off-switch behaviour.
- The app now owns two additional routing fields; see [Routing](DOCS.md#routing) before changing retry settings in a panel.
- Add a build-gating [retry check](DOCS.md#retries-before-output).
- CLIProxyAPI remains at 8.0.10.

# 8.0.10-2

- Add an optional, read-only diagnostics endpoint on port 18318 that lists recent failed requests: time, model, provider, account label or short hash, upstream status, error class, a fixed description of that class, streaming, output tokens, duration and request ID. It never returns prompts, responses, provider error messages, headers, keys or emails. It is off until you set the new `diagnostics_keys` option, separate keys that the API and panels do not accept, even with surrounding spaces.
- Diagnostics reads CPA Manager Plus's request history and answers `503 unavailable` when that interface is missing or changed, including changed fields, types or filtering. The proxy and CPA Manager Plus keep running when diagnostics fails or stops.
- A separate CI check runs diagnostics against the pinned CLIProxyAPI and CPA Manager Plus releases on every build, including update pull requests. Upstream updates stay plain version and checksum bumps.
- CLIProxyAPI remains at 8.0.10.

# 8.0.10-1

- Update CLIProxyAPI to 8.0.10; upstream checksum pinned.

# 8.0.4-6

- Add the `blocked_models` app option, a list of exact model IDs without a credential prefix, applied at every start. By default it blocks GPT-6 Sol and GPT-5.6 Sol (`gpt-6-sol`, `gpt-5.6-sol`, and Devin's own `devin/gpt-6-sol` and `devin/gpt-5-6-sol`). Blocked models are hidden from the model list and refused for OAuth accounts and provider API keys, also under any credential prefix such as `work/gpt-6-sol`. On a provider API key, the app also hides each model alias or name that a request, with or without a thinking suffix such as `(high)`, can send to a blocked model. Other models, including `gpt-6.1-sol`, keep working.
- The app now owns the `excluded-models` lists in `oauth` and on provider API keys, and rewrites them from the option at every start. Manual exclusions there are replaced, and an empty list clears them. A provider API key added in the management panel is covered from the next restart.
- CLIProxyAPI 8.0.4 cannot exclude models from `openai-compatibility` providers or from plugins. An OAuth model alias named after a blocked model is still listed, and serves the model it aliases. An OAuth model alias whose target is a blocked model, in `oauth.model-alias` or in an account's auth file, can still send requests to the blocked model: remove every such alias. See the documentation.
- CLIProxyAPI remains at 8.0.4.

# 8.0.4-5

- Bundle CPA Manager Plus 1.14.2 (Full Mode Manager Server), upstream checksum pinned, on port 18317. **Open Web UI** now opens it; the stock panel stays on port 8317.
- CPA Manager Plus logs in with the management password and connects to the proxy automatically. Its data lives in `/data/cpa-manager-plus/`.
- Startup rejects a management password with leading or trailing spaces, and stops if CPA Manager Plus cannot take a changed management password.
- Turn CLIProxyAPI usage statistics on by default for CPA Manager Plus monitoring, unless switched off in a panel.
- Daily workflow proposes CPA Manager Plus updates in a pull request.
- CLIProxyAPI remains at 8.0.4.

# 8.0.4-4

- Add routing app options, applied at every start: session affinity on with a 1-hour idle binding, round-robin (or fill-first) spread of new conversations, and retrying a failed request on your other accounts. CLIProxyAPI still moves a conversation to another account after a quota or other credential failure.
- CLIProxyAPI remains at 8.0.4.

# 8.0.4-3

- Document session-affinity routing with a secret-free example.
- CLIProxyAPI remains at 8.0.4.

# 8.0.4-2

- Publish the Home Assistant repository and installation instructions.
- CLIProxyAPI remains at 8.0.4.

# 8.0.4-1

- First amd64 Home Assistant app release with pinned CLIProxyAPI 8.0.4.
- Persistent provider configuration, OAuth credentials and authenticated LAN management.
