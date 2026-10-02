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
