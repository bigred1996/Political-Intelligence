"""Build explicit cross-record links after large imports.

The deterministic graph already infers shared-entity relationships. This module
materializes links that need source-specific identifiers or parsing: Hansard
speaker IDs to MPs, bill mentions inside full transcripts, and recorded-vote
participants to MPs from archived ourcommons.ca XML.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from api.config import settings

_MEMBER_ID_RE = re.compile(r"\((\d+)\)\s*$")
_BILL_RE = re.compile(r"\bBill\s+([CS])[-\s]+(\d{1,4})\b", re.I)
_SQLITE_PREFIX = "sqlite+aiosqlite:///"


def sqlite_path(database_url: str | None = None) -> Path:
    url = database_url or settings.database_url
    if not url.startswith(_SQLITE_PREFIX):
        raise ValueError("record linker currently supports local SQLite DATABASE_URL values")
    raw = url.removeprefix(_SQLITE_PREFIX)
    return Path(raw).resolve() if raw.startswith("/") else (Path.cwd() / raw).resolve()



_TITLE_RE = re.compile(r"^(Right\s+Hon\.|Hon\.|Mr\.|Mrs\.|Ms\.|Miss|Dr\.)\s+", re.I)
_GENERIC_ROLE_RE = re.compile(r"^(the\s+)?(speaker|deputy speaker|assistant deputy speaker|chair|assistant deputy chair)$", re.I)


def normalize_person_name(name: str | None) -> str | None:
    if not name:
        return None
    stripped = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in stripped if not unicodedata.combining(ch))
    stripped = re.sub(r"\s+", " ", stripped).strip().lower()
    return stripped or None


def parse_hansard_speaker_name(speaker: str | None) -> str | None:
    if not speaker:
        return None
    value = re.sub(r"\s+", " ", speaker).strip(" :")
    paren = re.search(r"\(([^()]+)\)", value)
    if value.lower().startswith("the ") and paren:
        value = paren.group(1).strip()
    else:
        value = re.sub(r"\s+\([^()]*\)\s*$", "", value).strip()
    value = _TITLE_RE.sub("", value).strip()
    value = re.sub(r",\s*(MP|M\.P\.).*$", "", value, flags=re.I).strip()
    if not value or _GENERIC_ROLE_RE.match(value) or len(value.split()) < 2:
        return None
    return value

def extract_commons_member_id(url: str | None) -> str | None:
    if not url:
        return None
    match = _MEMBER_ID_RE.search(url.strip())
    return match.group(1) if match else None


def bill_mentions(*texts: str | None) -> set[str]:
    mentions: set[str] = set()
    for text in texts:
        if not text:
            continue
        for prefix, number in _BILL_RE.findall(text):
            mentions.add(f"{prefix.upper()}-{int(number)}")
    return mentions


def parse_vote_participants_xml(content: bytes) -> list[dict[str, str | None]]:
    root = ET.fromstring(content)
    out: list[dict[str, str | None]] = []
    for participant in root.findall("VoteParticipant"):
        person_id = (participant.findtext("PersonId") or "").strip()
        if not person_id:
            continue
        first = (participant.findtext("PersonOfficialFirstName") or "").strip()
        last = (participant.findtext("PersonOfficialLastName") or "").strip()
        out.append({
            "person_id": person_id,
            "vote": (participant.findtext("VoteValueName") or "").strip() or None,
            "name": " ".join(part for part in [first, last] if part) or None,
            "party": (participant.findtext("CaucusShortName") or "").strip() or None,
            "riding": (participant.findtext("ConstituencyName") or "").strip() or None,
        })
    return out


def _chunks(rows: Iterable[tuple[Any, ...]], size: int = 10000) -> Iterator[list[tuple[Any, ...]]]:
    batch: list[tuple[Any, ...]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _create_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS record_links (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            source_table VARCHAR(64) NOT NULL,
            source_pk INTEGER NOT NULL,
            target_table VARCHAR(64) NOT NULL,
            target_pk INTEGER NOT NULL,
            relationship VARCHAR(64) NOT NULL,
            confidence FLOAT NOT NULL DEFAULT 1.0,
            evidence JSON,
            ingested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_record_link UNIQUE (
                source_table, source_pk, target_table, target_pk, relationship
            )
        );
        CREATE INDEX IF NOT EXISTS ix_record_links_source ON record_links (source_table, source_pk);
        CREATE INDEX IF NOT EXISTS ix_record_links_target ON record_links (target_table, target_pk);
        CREATE INDEX IF NOT EXISTS ix_record_links_relationship ON record_links (relationship);
        """
    )


def _insert_links(conn: sqlite3.Connection, rows: Iterable[tuple[Any, ...]]) -> int:
    before = conn.total_changes
    for batch in _chunks(rows):
        conn.executemany(
            """
            INSERT OR IGNORE INTO record_links (
                source_table, source_pk, target_table, target_pk, relationship, confidence, evidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
    conn.commit()
    return conn.total_changes - before


def _politician_member_map(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for pk, commons_url in conn.execute("SELECT id, commons_url FROM politicians WHERE commons_url IS NOT NULL"):
        member_id = extract_commons_member_id(commons_url)
        if member_id:
            out[member_id] = int(pk)
    return out


def _politician_name_map(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for pk, name in conn.execute("SELECT id, name FROM politicians WHERE name IS NOT NULL"):
        norm = normalize_person_name(name)
        if norm:
            out[norm] = int(pk)
    return out


def link_hansard_speakers(conn: sqlite3.Connection) -> int:
    member_to_pk = _politician_member_map(conn)
    name_to_pk = _politician_name_map(conn)

    def rows() -> Iterator[tuple[Any, ...]]:
        for speech_id, member_id, speaker in conn.execute(
            """
            SELECT id, speaker_db_id, speaker
            FROM hansard_speeches
            WHERE speaker IS NOT NULL AND speaker != ''
            """
        ):
            target_pk = member_to_pk.get(str(member_id)) if member_id else None
            parsed_name = parse_hansard_speaker_name(speaker)
            confidence = 1.0
            if not target_pk and parsed_name:
                target_pk = name_to_pk.get(normalize_person_name(parsed_name) or "")
                confidence = 0.92
            if target_pk:
                yield (
                    "hansard_speeches", int(speech_id), "politicians", target_pk,
                    "spoken_by", confidence,
                    json.dumps({"speaker_db_id": str(member_id) if member_id else None, "speaker": speaker, "parsed_name": parsed_name}),
                )

    return _insert_links(conn, rows())


def link_hansard_bills(conn: sqlite3.Connection) -> int:
    bills: dict[tuple[str, str], int] = {}
    parliament_codes: set[str] = set()
    for bill_id, bill_number, parliament in conn.execute(
        "SELECT id, bill_number, parliament FROM bills WHERE bill_number IS NOT NULL AND parliament IS NOT NULL"
    ):
        code = str(parliament)
        bills[(code, str(bill_number).upper())] = int(bill_id)
        parliament_codes.add(code)

    def rows() -> Iterator[tuple[Any, ...]]:
        for speech_id, parliament, session, subject, content in conn.execute(
            """
            SELECT id, parliament, session, subject, content
            FROM hansard_speeches
            WHERE subject LIKE '%Bill %' OR content LIKE '%Bill %'
            """
        ):
            parl_code = f"{parliament}-{session}"
            if parl_code not in parliament_codes:
                continue
            for bill_number in bill_mentions(subject, content):
                target_pk = bills.get((parl_code, bill_number))
                if target_pk:
                    yield (
                        "hansard_speeches", int(speech_id), "bills", target_pk,
                        "mentions_bill", 0.95,
                        json.dumps({"bill_number": bill_number, "parliament": parl_code}),
                    )

    return _insert_links(conn, rows())


def _raw_vote_file(raw_root: Path, parliament: int, session: int, vote_number: int) -> Path | None:
    name = f"votes_{parliament}_{session}_{vote_number}.xml"
    matches = sorted(raw_root.glob(f"parliament/house_votes_p{parliament}s{session}/**/{name}"))
    if not matches:
        matches = sorted(raw_root.glob(f"parliament/house_votes/**/{name}"))
    return matches[-1] if matches else None


def link_vote_participants(conn: sqlite3.Connection, raw_root: Path) -> int:
    member_to_pk = _politician_member_map(conn)

    def rows() -> Iterator[tuple[Any, ...]]:
        vote_rows = conn.execute(
            """
            SELECT id, raw
            FROM source_records
            WHERE source = 'house_votes' AND raw IS NOT NULL
            """
        )
        for vote_pk, raw_json in vote_rows:
            try:
                raw = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            path = _raw_vote_file(
                raw_root, int(raw.get("parliament") or 0), int(raw.get("session") or 0),
                int(raw.get("vote_number") or 0),
            )
            if not path:
                continue
            for participant in parse_vote_participants_xml(path.read_bytes()):
                target_pk = member_to_pk.get(str(participant["person_id"]))
                if not target_pk:
                    continue
                yield (
                    "source_records", int(vote_pk), "politicians", target_pk,
                    "mp_voted", 1.0,
                    json.dumps(participant),
                )

    return _insert_links(conn, rows())


def build_links(db_path: Path | None = None, raw_root: Path | None = None) -> dict[str, int]:
    db_path = db_path or sqlite_path()
    raw_root = raw_root or (db_path.parent / "data" / "raw")
    with sqlite3.connect(db_path) as conn:
        _create_table(conn)
        conn.execute("PRAGMA busy_timeout = 10000")
        counts = {
            "hansard_speaker_links": link_hansard_speakers(conn),
            "hansard_bill_links": link_hansard_bills(conn),
            "vote_participant_links": link_vote_participants(conn, raw_root),
        }
        counts["total_record_links"] = conn.execute("SELECT COUNT(*) FROM record_links").fetchone()[0]
        return counts
