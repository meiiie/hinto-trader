# Contributing

Thanks for helping improve Hinto.

## Ground Rules

- Keep `ENV=paper` as the default for examples and tests.
- Never commit real API keys, tokens, PEM files, local databases, generated CSVs,
  screenshots with credentials, or exchange account details.
- Run the secret scan before opening a pull request:

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\secret-scan.ps1
  ```

- Add or update tests when changing trading logic, execution behavior, risk
  controls, or persistence contracts.
- Keep pull requests focused. Trading systems are easier to review when changes
  are small and behavior is explicit.

## Development Setup

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_backend.py
```

Frontend:

```powershell
cd frontend
npm ci
npm run dev
```

## Pull Request Checklist

- Secret scan passes.
- Frontend build passes if UI files changed.
- Backend tests or targeted smoke tests were run when backend behavior changed.
- Documentation was updated when configuration or workflows changed.
- The change keeps live trading opt-in.
