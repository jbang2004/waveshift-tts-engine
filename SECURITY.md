# Security Policy

## Supported Versions

This project is pre-1.0. Security fixes are applied to the `main` branch until
tagged releases are introduced.

## Reporting a Vulnerability

Please do not open a public issue for vulnerabilities.

Report privately by emailing the maintainer account associated with the GitHub
profile, or by opening a GitHub security advisory if available for this repository.

Include:

- affected file or endpoint
- impact summary
- reproduction steps using sanitized data
- whether credentials, media URLs, or task payloads may be exposed

Do not include:

- API tokens
- Cloudflare account secrets
- private R2 object URLs
- downloaded user media
- raw production task payloads

## Security Scope

High-priority security areas include:

- credential handling in `.env` and Cloudflare clients
- task data returned by debug endpoints
- public exposure of generated HLS objects
- path traversal or unsafe R2 object key handling
- user media retention and temporary file cleanup

## Operational Guidance

- Use least-privilege Cloudflare API tokens.
- Keep `.env` outside version control.
- Prefer development credentials for local testing.
- Disable or protect debug endpoints before exposing the service publicly.
- Rotate any credential that appears in logs, issues, commits, or screenshots.
