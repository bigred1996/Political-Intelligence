"""Deterministic sample lobbying records.

Used as a fallback so the end-to-end pipeline + frontend are testable offline,
independent of live government-site availability. Real pulls come from ocl.py's
live path; these mirror the same record shape so downstream code is identical.
"""
from __future__ import annotations

from typing import Any

# Keyed by a normalized (lowercased) substring of the company name.
SAMPLE_LOBBYING: dict[str, list[dict[str, Any]]] = {
    "telus": [
        {
            "registration_id": "OCL-2024-001234",
            "client": "TELUS Communications Inc.",
            "registrant": "Quintin Maple (in-house)",
            "subject_matters": ["Telecommunications", "Broadcasting", "Consumer Issues"],
            "institutions": ["Innovation, Science and Economic Development Canada", "CRTC"],
            "communication_date": "2024-11-12",
            "type": "in-house",
        },
        {
            "registration_id": "OCL-2024-001891",
            "client": "TELUS Communications Inc.",
            "registrant": "Earnscliffe Strategy Group (consultant)",
            "subject_matters": ["Spectrum Auction", "Broadband Infrastructure"],
            "institutions": ["Office of the Minister of Industry", "House of Commons"],
            "communication_date": "2025-02-03",
            "type": "consultant",
        },
    ],
    "rogers": [
        {
            "registration_id": "OCL-2024-004412",
            "client": "Rogers Communications Canada Inc.",
            "registrant": "Susan Helstab (in-house)",
            "subject_matters": ["Telecommunications", "Mergers and Acquisitions"],
            "institutions": ["Competition Bureau", "ISED"],
            "communication_date": "2024-09-30",
            "type": "in-house",
        },
    ],
    "loblaw": [
        {
            "registration_id": "OCL-2025-000777",
            "client": "Loblaw Companies Limited",
            "registrant": "Crestview Strategy (consultant)",
            "subject_matters": ["Grocery Code of Conduct", "Food Prices", "Competition"],
            "institutions": ["Agriculture and Agri-Food Canada", "House of Commons Standing Committee on Agriculture"],
            "communication_date": "2025-01-21",
            "type": "consultant",
        },
    ],
}


def sample_for(company_name: str) -> list[dict[str, Any]]:
    norm = company_name.lower().strip()
    for key, records in SAMPLE_LOBBYING.items():
        if key in norm:
            return records
    return []
