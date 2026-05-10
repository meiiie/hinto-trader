# Security Policy

## Secrets

Do not commit real `.env`, `.env.production`, `.env.local`, PEM, private key, API token, Telegram token, or exchange credential files.

Use `.env.example` files as templates only. Production values must come from local environment files, deployment secrets, or the target server environment.

Before making the repository public:

1. Run `powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/secret-scan.ps1`.
2. Rotate any Binance, Telegram, AWS, Lambda, Docker, or SSH credentials that have ever appeared in the repository.
3. If the existing Git history will be published, scrub historical secrets with a history-rewrite tool or publish a fresh clean repository.

## Trading Safety

Default local mode should be `paper`. Live trading requires explicit local configuration and real exchange credentials.
