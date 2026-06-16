# Polaris MCP Server

Exposes all Polaris data sources as callable tools for Claude and any MCP-compatible LLM.

## Setup

### In Claude Code

Add to `~/.claude/settings.json` (or the project-level `.claude/settings.json`):

```json
{
  "mcpServers": {
    "polaris": {
      "command": "/Users/codymcmullen/Documents/Claude Code/polaris/.venv/bin/python",
      "args": ["/Users/codymcmullen/Documents/Claude Code/polaris/mcp-servers/polaris_server.py"]
    }
  }
}
```

### In any other MCP client (stdio transport)

```bash
cd polaris
.venv/bin/python mcp-servers/polaris_server.py
```

## Tools

| Tool | Description |
|---|---|
| `list_data_sources` | All sources and their current record counts |
| `gather_company_evidence` | **Primary tool** — full cross-source evidence bundle for a company |
| `get_risk_scores` | Four 0–10 political risk scores with drivers |
| `compare_companies` | Side-by-side risk comparison of two companies |
| `search_lobbying` | OCL lobbying communications — who lobbied, where, on what |
| `search_ocl_registrations` | Lobbying registration filings — formal declarations |
| `search_contracts` | Federal contracts awarded to a company |
| `search_grants` | Grants & Contributions received |
| `search_donations` | Political donations linked to a company or person |
| `search_bills` | Bills before Parliament by keyword |
| `search_regulations` | Canada Gazette entries (proposed + final regulations) |
| `search_tribunal_decisions` | CRTC and Competition Bureau decisions |
| `search_appointments` | GIC appointments to regulatory bodies |
| `search_hansard` | Hansard speeches mentioning a company or topic |
| `search_politicians` | MP directory by name, party, or province |

## Recommended workflow for LLM due diligence

1. `gather_company_evidence("Rogers Communications", sector="telecom")` — get everything
2. `get_risk_scores("Rogers Communications", sector="telecom")` — quantified risk
3. `search_tribunal_decisions("Rogers")` — any CRTC proceedings
4. `search_regulations("broadcasting telecom spectrum")` — pending regulatory changes
5. `search_appointments(keywords="", organization="CRTC")` — who's running the regulator
6. `compare_companies("Rogers Communications", "BCE Inc", sector="telecom")` — relative risk
