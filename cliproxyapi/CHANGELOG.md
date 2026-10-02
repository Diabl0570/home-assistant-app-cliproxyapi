# 8.0.4-6

- Add the `blocked_models` app option, a list of exact model IDs without a credential prefix, applied at every start. By default it blocks GPT-6 Sol and GPT-5.6 Sol (`gpt-6-sol`, `gpt-5.6-sol`, and Devin's own `devin/gpt-6-sol` and `devin/gpt-5-6-sol`). Blocked models are hidden from the model list and refused for OAuth accounts and provider API keys, also under any credential prefix such as `work/gpt-6-sol`. This includes API key models that name a blocked model under an alias or with a thinking suffix such as `gpt-6-sol(high)`. Other models, including `gpt-6.1-sol`, keep working.
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
