# Contributing to HRPulsar

Thanks for your interest in contributing! This document explains how to get a
development environment running and what we expect from contributions.

## Development setup

Prerequisites: Python 3.14+, Node.js 22+, Docker.

```bash
git clone https://github.com/HRPulsar/hrpulsar.git
cd hrpulsar
cp .env.example .env
docker compose up -d      # PostgreSQL + Redis
make install-dev          # backend + frontend dependencies
make migrate              # database migrations
make run                  # backend (8100) + frontend (3100)
```

Useful targets: `make lint`, `make test-unit`, `make format`, `make seed-demo`
(demo dataset). Run `make help` for the full list.

## Making changes

- Open an issue first for anything beyond a trivial fix, so we can agree on
  the approach before you invest time.
- Fork the repository and create a branch from `main`.
- Keep pull requests focused: one logical change per PR.
- All code, comments, and documentation are in English.
- Add or update tests for any behavior change (`backend/tests/unit/`,
  frontend `src/__tests__/`, Playwright specs in `frontend/e2e/`).
- Backend dependencies are locked: edit `backend/requirements*.in`, then run
  `make lock` to regenerate the pinned `requirements*.txt` that Docker and CI
  install from, and commit both files.
- Run `make lint` and `make test-unit` before submitting; CI runs the same
  checks plus the frontend build and e2e suite.

## Commit messages

Use conventional-commit style prefixes (`fix:`, `feat:`, `chore:`, `docs:`)
with an optional module scope, e.g. `fix(assessment): …`.

## Licensing

HRPulsar Community Edition is licensed under AGPLv3 (see [LICENSE](LICENSE)
and [NOTICE](NOTICE)). By submitting a contribution you agree that it will be
distributed under the same license.

## Questions

Open a GitHub issue or reach us at support@hrpulsar.com.
