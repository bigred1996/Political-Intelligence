# Nessus Intelligence

Canadian political due-diligence platform. Enter a company → pull federal data
(lobbying, contracts, donations, bills) → score political risk → draft a 9-section
report → analyst review → customer report + PDF.

See `CLAUDE.md` for the full architecture and build status.

## Run

```bash
cd polaris
.venv/bin/python -m uvicorn api.main:app --reload --port 8077
# open http://127.0.0.1:8077
```

## Quick demo (from the dashboard)

1. **Data Sources** → *Ingest bills* and *Ingest donations* (contracts auto-cache on first contract scan).
2. **Federal Contracts** → *Ingest live contracts* (streams real open.canada.ca data).
3. **Generate Political Risk Report** → company `TELUS`, sector `telecommunications` → *Generate report*.
4. Click **View ↗** to open the branded report, or **Approve** to mark it delivered.

## Data sources (all Government of Canada open data)

| Source | Path | Status |
|---|---|---|
| Federal contracts >$10k | open.canada.ca CSV (streamed) | real |
| Political contributions | Elections Canada ZIP (cached, streamed) | real |
| Bills | LEGISinfo JSON API | real |
| Lobbying registry | OCL bulk ZIP | sample fallback (gov endpoint blocked) |

## AI report drafting

Sections render via a deterministic **evidence template** by default. Set a real
`ANTHROPIC_API_KEY` in `.env` and the builder switches each section to Claude
(`claude-sonnet-4-6`) automatically — prompts live in `/prompts`.

## Test

```bash
.venv/bin/python -m pytest tests/ -q
```
