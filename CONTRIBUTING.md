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

## Contributing a translation

The interface ships with English (`en`, the fallback) and German (`de`).
Adding a language is mostly a translation-catalog change:

1. Copy `frontend/messages/en.json` to `frontend/messages/<lang>.json` and
   translate the values. Keep every key, every ICU placeholder (`{name}`,
   `{count, plural, ...}`), and every rich-text tag (`<b>…</b>`) intact —
   reorder them freely, but do not drop or rename them.
2. Copy `backend/app/i18n/en.json` to `backend/app/i18n/<lang>.json` and
   translate it the same way (backend error messages and email strings).
3. Register the locale in three places: `CATALOG_LOCALES` and
   `LOCALE_LABELS` in `frontend/src/lib/locale.ts`, and the `CATALOGS` map
   in `frontend/src/i18n/request.ts`.
4. Run the guards — they enforce key and placeholder parity with `en`:
   `cd frontend && npx vitest run` and
   `cd backend && python -m pytest tests/unit/test_i18n_coverage.py`.
5. Test-drive with `AVAILABLE_LOCALES=en,<lang>` (backend) and
   `NEXT_PUBLIC_AVAILABLE_LOCALES=en,<lang>` (frontend), walk the main
   screens, and fix text that overflows buttons, tabs, or table headers —
   prefer a shorter translation over a layout change.
6. Fix a glossary for your language before you start (how the product terms
   translate — vacancy vs position, exam vs review, formal vs informal
   address) and apply it consistently.

Two areas need small backend additions we are happy to help with in the PR:
notification templates stored in the database (a seed migration per locale)
and the AI content-language option. Open an issue if you want a language and
don't want to do the wiring yourself.

## Commit messages

Use conventional-commit style prefixes (`fix:`, `feat:`, `chore:`, `docs:`)
with an optional module scope, e.g. `fix(assessment): …`.

## Licensing

HRPulsar Community Edition is licensed under AGPLv3 (see [LICENSE](LICENSE)
and [NOTICE](NOTICE)). By submitting a contribution you agree that it will be
distributed under the same license.

## Questions

Open a GitHub issue or reach us at support@hrpulsar.com.
