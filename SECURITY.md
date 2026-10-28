# Security

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub: **Security → Report a vulnerability**
on this repository. Do not open a public issue. I aim to respond within a week. Only the
latest commit on `main` is supported.

## Threat model

This server holds a Mattermost token or password with full access to one account and acts on
behalf of an AI model. The main risks, and what the server does about each, are below.

### Prompt injection through message content

Anyone who can post in a channel you are in, or DM you, controls text that reaches the model.
A malicious message may try to make the model post somewhere, exfiltrate files or edit messages.

- The server instructions tell the model to treat message content as untrusted data, and to
  show you the exact target and text for confirmation before `send_message` or `edit_message`.
- Tools are annotated (`readOnlyHint` / `destructiveHint`), so clients can require approval
  for anything that writes.
- Deleting messages is not implemented. `edit_message` refuses posts by other users, and
  reading never changes unread state.

These are mitigations, not guarantees. Keep tool-call approval on in your client for
`send_message` and `edit_message`.

### Local file access

`send_message` reads local files to attach, and `download_file` writes files. Both are confined:

- **Reads** must resolve, after following symlinks, into a directory listed in
  `MATTERMOST_UPLOAD_DIRS`. The default is your home directory and the downloads directory.
- **Writes** go only into `MATTERMOST_DOWNLOADS_DIR` or its subdirectories. Files are created
  with `O_EXCL`, so an existing file is never overwritten and a symlink at the target name, even
  a dangling one, is never followed.
- **Size**: downloads are streamed to disk and capped at `MATTERMOST_MAX_DOWNLOAD_MB` (default
  100) on the bytes actually received; an oversized file is refused and the partial file removed.
  A message takes at most 10 attachments.
- Hidden paths (any component starting with `.`, such as `~/.ssh` or `~/.config`) and the
  server's own config file are always refused.
- File names from the server are sanitized: no path separators, no leading dots. File ids are
  validated before they go into an API path, and every other path segment is URL-encoded.

If your upload directories hold sensitive files that are not hidden, narrow
`MATTERMOST_UPLOAD_DIRS`.

### HTTP mode (`--http`)

- The server listens on `127.0.0.1` by default. On any other address it prints a warning: the
  transport is plain HTTP, so put a TLS-terminating proxy in front of it.
- A bearer token (`MATTERMOST_MCP_TOKEN`, at least 16 characters) is mandatory. The server refuses
  to start without one. Tokens are compared in constant time, and every path requires one.
- On loopback, Host and Origin headers are validated, which blocks DNS rebinding. CORS is not
  enabled, so browser pages cannot call the server.
- Request bodies are limited to 4 MiB, and access logging is off.

### Credentials

- Credentials are read from environment variables or a local `.env` file (keep it
  `chmod 600`). They are never logged or returned in tool results.
- TLS certificate verification is on by default (`MATTERMOST_VERIFY_SSL=false` is for lab
  servers only).
- A `MATTERMOST_TOKEN` is never logged out by the server, so your browser session or PAT stays
  valid. Password logins create a separate session that is logged out on exit.

## Security testing

CI runs on every push and pull request, and weekly to catch new CVEs:

| Kind | Tools |
|---|---|
| SAST | ruff (flake8-bandit rules), bandit, semgrep (`p/python`, `p/security-audit`, `p/secrets`, `p/owasp-top-ten`), CodeQL `security-extended` |
| DAST | `tests/test_http_dast.py`: a real server process probed for auth bypass, DNS rebinding, CORS, oversized and malformed requests, forged sessions, path escapes and credential leaks |
| SCA | pip-audit (OSV) against the hashed lockfile `server.py.lock` |
| Secrets | gitleaks over the full git history, plus a pre-commit hook |

GitHub Actions are pinned to commit SHAs, and Dependabot keeps them current.
