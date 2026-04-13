# Contributing to RepoRanger 🌳

We welcome contributions! As a "Park Ranger" for code, we maintain high standards for hygiene and security.

## Development Setup

1. Clone the repo: `git clone https://github.com/shrujaya/repo-ranger`
2. Install Dispatcher deps: `cd apps/dispatcher && pip install -r requirements.txt`
3. Install Worker deps: `cd worker && pip install -r requirements.txt`

## Coding Standards
- **Strict Typing**: Use Python type hints for all functions.
- **Async First**: Use `httpx` and `AsyncGroq` for all external calls.
- **Zero Knowledge**: Never implement features that require the Dispatcher to store user API keys.

## Pull Requests
1. Fork the repo.
2. Create a feature branch.
3. Submit a PR with a clear description of the "Hygiene" benefit.
