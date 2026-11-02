# Security policy

EcoGuard is a reproducible educational evidence pipeline, not a production banking, legal-advice or customs system. The local API has no authentication and must remain bound to a trusted interface such as `127.0.0.1`.

## Supported versions

Only the newest tagged release receives security fixes. GitHub Releases and tags are the supported distribution boundary; `main` may contain unreleased changes.

## Dependency maintenance

Routine Dependabot version-update PRs are disabled for all ecosystems to keep
the verified environment stable. Vulnerability alerts remain enabled. Automatic
security-fix PR creation is a separate GitHub setting and is currently disabled;
this policy does not enable it. A fixed version is not a promise that future
vulnerabilities cannot be discovered. Security changes are reviewed and pinned explicitly, then checked
by the core release gate and, where relevant, the research replay/retraining gates.

The 2026-11-02 dependency fixes on `main` pin Pillow 13.0.0, Black 26.10.1 and
setuptools 84.2.1. For a new development or research environment, use this patched
source tree and record its commit SHA. The original `v0.6.0` tag remains an
immutable historical reproducibility reference and does not acquire these fixes
retroactively. The dependency-free core wheel does not install these packages;
the affected pins belong to build/development tooling and optional research.

## Reporting

Use [GitHub private vulnerability reporting](https://github.com/soccz/EcoGuard/security/advisories/new) for a suspected vulnerability. Do not open a public issue containing exploit details, personal data, credentials, private documents or production endpoints.

Useful reports include:

- affected tag and commit SHA
- minimal synthetic reproduction
- expected and observed evidence-boundary behavior
- whether malformed input bypasses provenance, unit, source or human-review controls

## Explicit non-goals

The repository does not promise tenant isolation, network authentication, encrypted storage, malware scanning, regulated retention or production availability. See [operations and production boundary](docs/OPERATIONS.md) for the controls a real service would need.
