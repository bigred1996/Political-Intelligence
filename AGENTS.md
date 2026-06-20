# Repository Guidelines

## Project Structure & Module Organization

Nessus is a Canada-first political due-diligence product. The FastAPI backend is in `api/`, with routes in `api/routes/` and SQLAlchemy models in `api/models/`. Ingestion, evidence gathering, report generation, and sector intelligence live in `pipeline/`; hybrid search lives in `search/`; source scrapers live in `scrapers/`. The main Next.js product UI is `web/`. The older internal operations console is `frontend/index.html`, served at `/internal`. Tests are in `tests/`; prompts are in `prompts/`; local runtime artifacts are under `data/`, `reports/`, and `logs/`.

## Build, Test, and Development Commands

Run the backend API on port `8077`:

```bash
.venv/bin/python -m uvicorn api.main:app --reload --port 8077
```

Run the product UI:

```bash
cd web && npm run dev
```

Build and type-check the UI:

```bash
cd web && npm run build
```

Lint the UI:

```bash
cd web && npm run lint
```

Run backend tests:

```bash
.venv/bin/python -m pytest tests/ -q
```

Rebuild semantic search after text-source ingests:

```bash
curl -X POST http://127.0.0.1:8077/api/search/reindex
```

## Coding Style & Naming Conventions

Use Python 3.11 style with type hints, small deterministic helpers, and explicit API response models from `api/schemas.py`. Keep large-table lookups indexed by `canonical_name`; avoid broad `ILIKE` scans on large sources. Frontend code uses TypeScript, Next App Router conventions, typed API helpers in `web/lib/api.ts`, and reusable components in `web/components/`. Prefer descriptive kebab-case route folders and PascalCase React components.

## Testing Guidelines

Use `pytest`; name tests `test_*.py`. Keep tests local and network-free. Add contract tests when changing API shapes, source coverage, evidence references, record links, scheduler behavior, search results, or report output. For frontend changes, `npm run build` is the main TypeScript and route validation check.

## Commit & Pull Request Guidelines

History currently has only an initial commit, so use clear imperative messages such as `Add source quality rollup` or `Tighten sector evidence links`. PRs should include a short summary, verification commands, data/schema implications, linked issues when relevant, and screenshots for visible UI changes.

## Security & Configuration Tips

Do not commit API keys, private customer data, or generated secrets. Use `.env` based on `.env.example`. Paid AI must remain optional; deterministic reports and local embeddings should work without `ANTHROPIC_API_KEY`.
