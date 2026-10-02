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
