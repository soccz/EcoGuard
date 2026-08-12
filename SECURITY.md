# Security policy

EcoGuard is a reproducible educational evidence pipeline, not a production banking, legal-advice or customs system. The local API has no authentication and must remain bound to a trusted interface such as `127.0.0.1`.

## Supported versions

Only the newest tagged release receives security fixes. GitHub Releases and tags are the supported distribution boundary; `main` may contain unreleased changes.

## Reporting

Use [GitHub private vulnerability reporting](https://github.com/soccz/EcoGuard/security/advisories/new) for a suspected vulnerability. Do not open a public issue containing exploit details, personal data, credentials, private documents or production endpoints.

Useful reports include:

- affected tag and commit SHA
- minimal synthetic reproduction
- expected and observed evidence-boundary behavior
- whether malformed input bypasses provenance, unit, source or human-review controls

## Explicit non-goals

The repository does not promise tenant isolation, network authentication, encrypted storage, malware scanning, regulated retention or production availability. See [operations and production boundary](docs/OPERATIONS.md) for the controls a real service would need.
