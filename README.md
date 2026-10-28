# mattermost-mcp

An [MCP](https://modelcontextprotocol.io) server for [Mattermost](https://mattermost.com)
(REST API v4). The assistant can see what's unread and whose turn it is to reply, read
channels and threads, search, post, react and mark things read.

It is a single file, `server.py`, run with [uv](https://docs.astral.sh/uv/). Its dependencies
are declared inline (PEP 723) and pinned in `server.py.lock`, so you don't need a virtualenv.
The server runs over stdio by default, or as an always-on Streamable HTTP service with `--http`.

## Tools

| Tool | What it does |
|---|---|
| `get_unread` | Everything unread, grouped into DMs, @-mentions, channels and followed threads. Each conversation has a status: `awaiting_reply`, `awaiting_reply_stale`, `you_replied_last` or `unknown`. Stale conversations are collapsed to their last message |
| `list_channels` | Your channels and chats, filtered by type, unread or substring |
| `read_channel` | Recent messages, oldest first. Page back with `before` / `older_cursor`, or filter with `since` (`2026-10-20`, `36h`, `7d`) |
| `read_thread` | A whole thread, given any post in it |
| `search_posts` | Mattermost search syntax: `from:`, `in:`, `on:`, `before:`, `after:`, `"phrase"`, `-excluded` |
| `list_threads` | Threads you follow (needs Collapsed Reply Threads) |
| `find_users` | People search, with online/away/dnd/offline status |
| `download_file` | Save a message attachment into the downloads directory |
| `send_message` | Post to a channel or DM, reply in a thread, attach up to 10 files |
| `edit_message` | Edit one of your own messages |
| `react` | Add or remove an emoji reaction |
| `mark_read` | Mark a channel or thread as read |
| `get_me` | Connection check: the account and its teams |

You can name a channel by id, name or title (`~town-square`), as `@username` for a DM, or
by a Mattermost URL. You can name a post by id or permalink. Reading never marks anything as
read. Deleting messages is deliberately not supported. Every tool carries MCP annotations
(`readOnlyHint`, `destructiveHint`, …).

## Setup

```bash
mkdir -p ~/.config/mattermost-mcp
cp .env.example ~/.config/mattermost-mcp/.env
chmod 600 ~/.config/mattermost-mcp/.env
$EDITOR ~/.config/mattermost-mcp/.env
```

| Variable | Required | Meaning |
|---|---|---|
| `MATTERMOST_BASE_URL` | yes | Server URL, e.g. `https://mattermost.example.com` |
| `MATTERMOST_TOKEN` | one of the two | Personal Access Token, or a browser session token (cookie `MMAUTHTOKEN`). The server never logs it out |
| `MATTERMOST_LOGIN_ID` + `MATTERMOST_PASSWORD` | one of the two | Email/password login. The server creates its own session, renews it when it expires and logs out on exit |
| `MATTERMOST_MFA_TOKEN` | no | One-time MFA code, if MFA is on |
| `MATTERMOST_VERIFY_SSL` | no | `false` disables TLS verification (insecure, for self-signed lab servers only) |
| `MATTERMOST_DOWNLOADS_DIR` | no | Where files are saved (default `~/Downloads/mattermost`). Saving outside it is refused |
| `MATTERMOST_MAX_DOWNLOAD_MB` | no | Largest file `download_file` will save (default `100`) |
| `MATTERMOST_UPLOAD_DIRS` | no | `:`-separated directories that attachments may come from (default: your home and the downloads directory) |
| `MATTERMOST_MCP_TOKEN` | for `--http` | Bearer token clients must present, at least 16 characters |
| `MATTERMOST_MCP_HOST` / `MATTERMOST_MCP_PORT` | no | `--http` listen address, default `127.0.0.1:8732` |

Environment variables take precedence over the file. `MATTERMOST_MCP_CONFIG` points the
server at a different file.

## Running

### stdio (the client starts the server)

```bash
claude mcp add --scope user mattermost -- uv run --script /path/to/mattermost-mcp/server.py
```

### HTTP (the server runs on its own and clients connect to it)

```bash
# put the token into the config file as MATTERMOST_MCP_TOKEN=...
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
uv run --locked --script server.py --http
claude mcp add --scope user --transport http mattermost http://127.0.0.1:8732/mcp \
  --header "Authorization: Bearer <token>"
```

To keep the server running in the background, use a systemd user service. A template is in
[`contrib/mattermost-mcp.service`](contrib/mattermost-mcp.service):

```bash
cp contrib/mattermost-mcp.service ~/.config/systemd/user/   # adjust the path in ExecStart
systemctl --user daemon-reload
systemctl --user enable --now mattermost-mcp
loginctl enable-linger "$USER"   # start at boot, not at first login
```

## Security

Read [SECURITY.md](SECURITY.md). In short:

- Chat messages are untrusted input that can carry prompt injection.
- The server only reads and writes files inside the configured directories.
- The server instructs the model to confirm posts and edits with you first.
- HTTP mode listens on loopback by default and requires a bearer token.

## Development

```bash
uv export --script server.py --format requirements.txt --no-header > /tmp/requirements.txt
uv run --no-project --with-requirements /tmp/requirements.txt --with pytest --with 'httpx>=0.27' pytest -q
```

`tests/test_server.py` runs the tools against a fake Mattermost API (`httpx.MockTransport`).
`tests/test_http_dast.py` starts the real server in `--http` mode and probes it over the
network. It checks authentication, Host/Origin validation, body limits, malformed JSON-RPC
and file-path escapes. CI also runs ruff (with the bandit rules), bandit, semgrep, CodeQL,
pip-audit against the lockfile, and gitleaks over the full history. After changing the
dependencies in the script header, refresh the lockfile with `uv lock --script server.py`.

## License

[MIT](LICENSE)
