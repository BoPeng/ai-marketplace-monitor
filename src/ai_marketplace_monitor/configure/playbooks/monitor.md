---
section: monitor
summary: Global settings in the single [monitor] section, currently the proxy aimm's browser uses.
---
## Goal

A `[monitor]` section with the settings that apply to aimm as a whole: a proxy, which aimm's
browser uses to reach Facebook (it helps when Facebook blocks or limits the user's own
connection), and the update reminder.

## Subtasks

### Proxy

Ask for the proxy address from the user's proxy or VPN provider (`proxy_server`, for example
`http://proxy.example.com:8080`; it may also be a `${VAR}` reference). If the proxy needs an
account, `proxy_username` and `proxy_password` are references to environment variables
(`${PROXY_USERNAME}`, `${PROXY_PASSWORD}`); never ask for them in the chat. `proxy_bypass` only if
the user names hosts that should not use the proxy.

### Update reminder

aimm checks PyPI once a day and says in its log and the web UI when a newer release is out. Set
`check_updates = false` only if the user wants that off.

### Removing the proxy

To stop using a proxy, unset `proxy_server` (and the account fields).

## Completion

The section is complete when it says what the user wants; a `proxy_username` or
`proxy_password` needs a `proxy_server`.
