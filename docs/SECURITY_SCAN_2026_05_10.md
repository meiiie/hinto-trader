# Security Scan - 2026-05-10

Scope: open-source readiness check for the public Hinto repository.

## Threat Model

Hinto handles sensitive exchange and notification credentials through local
environment variables. The highest-risk public-release failures are committed
API keys, private deployment keys, runtime databases, logs, and live-mode
defaults that could execute real orders without explicit operator setup.

## Finding Discovery

Checks run:

- tracked-file secret scan: `scripts/secret-scan.ps1`
- tracked-file inventory for `.env`, `.pem`, `.key`, secret, credential, and
  SSH-key names
- raw pattern scan for private-key headers, AWS access keys, GitHub tokens, and
  OpenAI-style API keys

## Validation

Result:

- `Secret scan passed.`
- `git ls-files` does not include `.env`, PEM files, local databases, or
  generated runtime logs.
- Placeholder examples remain in `.env.example`, docs, and tests. These are
  non-secret placeholders.

## Attack Path Analysis

No committed live credential or private deployment key was found in the tracked
public tree.

Residual risks:

- Any key that ever appeared in the old private repository, chat, screenshot, or
  log should be rotated before live trading continues.
- Runtime DB/log exports must stay ignored and must not be attached to releases.

## Recommendation

Keep `.env` and deployment keys local, keep paper mode as the default, and run
`scripts/secret-scan.ps1` before every public release.
