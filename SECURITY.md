# Security policy

## Supported versions

The project is pre-1.0. Security fixes are applied to the latest release on
`main`; older snapshots are not maintained.

## Reporting a vulnerability

Please do not open a public issue for security problems. Use the repository's
**Security** tab to open a private advisory
(<https://github.com/Eduardo12Pacheco/ecuador-open-data-lakehouse/security/advisories/new>)
and include:

- the affected version and command,
- a minimal reproduction,
- the impact you expect.

You can expect an acknowledgement within a few days. Once a fix is available a
new release is published and the advisory is disclosed with credit, if desired.

## Design guarantees

- The tool runs locally and never requires credentials, API keys or accounts.
- Downstream downloads are restricted to an allow-list of public data hosts, and
  every file is verified against a pinned SHA-256 checksum before use.
- No secrets are stored in the repository; CI runs `gitleaks` over the full
  history and `pip-audit` over the locked dependencies.
