# Repository Guidelines

## Project Structure & Module Organization
This repo is split into `backend/` and `frontend/`. `backend/` is a Django project with shared settings in `backend/agdevops/` and domain apps in `backend/ops/`, `backend/cmdb/`, `backend/marketplace/`, and `backend/sqlaudit/`. `frontend/src/` contains the Vue app: page views in `frontend/src/views/`, shared layout in `frontend/src/layout/`, API wrappers in `frontend/src/api/`, router config in `frontend/src/router/`, and Pinia stores in `frontend/src/stores/`. Reference docs belong in `docs/`. Treat `frontend/dist/`, `frontend/node_modules/`, `backend/__pycache__/`, and `db.sqlite3` as generated artifacts.

## Build, Test, and Development Commands
- `cd backend && pip install -r requirements.txt` installs Python dependencies.
- `cd backend && python manage.py migrate` applies local database migrations.
- `cd backend && python manage.py seed_data` loads demo data for dashboards and CRUD pages.
- `cd backend && python -m daphne -b 0.0.0.0 -p 8000 agdevops.asgi:application` runs the ASGI backend with WebSocket support.
- `cd backend && python manage.py test` runs Django test suites in each app's `tests.py`.
- `cd frontend && npm install` installs the Vite/Vue toolchain.
- `cd frontend && npm run dev` starts the UI on `http://localhost:3000`.
- `cd frontend && npm run build` creates a production bundle; use `npm run preview` for a local smoke test.

## Coding Style & Naming Conventions
Follow existing conventions: Python uses 4-space indentation, snake_case modules, and app-local helpers. Vue components in `frontend/src/views/` and `frontend/src/layout/` use PascalCase filenames such as `NginxManage.vue`; API and store modules use lower-case filenames such as `request.js` and `app.js`. No formatter or linter is committed, so match the surrounding file and remove unused imports.

## Testing Guidelines
Backend tests use Django's built-in `TestCase`; add coverage in the nearest app-level `tests.py` or a `test_*.py` module. Name tests by behavior, for example `test_refresh_info_marks_host_offline_on_ssh_failure`. Frontend has no automated test suite yet, so every UI change should at minimum pass `npm run build` and a manual browser check.

## Commit & Pull Request Guidelines
Use the commit style already in history: `feat: ...`, `feat(scope): ...`, `style(scope): ...`, `docs: ...`. Keep subjects imperative and scoped to one change. PRs should describe the user-visible impact, list touched areas, include validation steps, and attach screenshots for UI updates.

## Security & Configuration Tips
`backend/agdevops/settings.py` is configured for local development (`DEBUG = True`, open CORS, SQLite). Do not commit production secrets, real credentials, or environment-specific hostnames. If you change backend Python code while using Daphne, restart the server manually because hot reload is not enabled.
