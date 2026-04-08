"""SQLite database for saved founder profiles."""

import json
import sqlite3
import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


DB_PATH = Path(__file__).parent / "founders.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create the saved_founders table if it doesn't exist."""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS saved_founders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            company TEXT,
            role TEXT,
            industry TEXT,
            stage TEXT,
            date_founded TEXT,
            product TEXT,
            product_desc TEXT,
            product_eval TEXT,
            source TEXT,
            url TEXT,
            overall_score REAL,
            card TEXT,
            enrichment TEXT,
            linkedin TEXT,
            notes TEXT DEFAULT '',
            saved_at TEXT NOT NULL,
            search_query TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_founder(data: Dict) -> int:
    """Save a founder profile. Returns the row id."""
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO saved_founders
           (name, company, role, industry, stage, date_founded, product,
            product_desc, product_eval, source, url, overall_score,
            card, enrichment, linkedin, notes, saved_at, search_query)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data.get("name", ""),
            data.get("company"),
            data.get("role"),
            data.get("industry"),
            data.get("stage"),
            data.get("date_founded"),
            data.get("product"),
            data.get("product_desc"),
            json.dumps(data.get("product_eval")) if data.get("product_eval") else None,
            data.get("source"),
            data.get("url"),
            data.get("overall_score"),
            json.dumps(data.get("card")) if data.get("card") else None,
            json.dumps(data.get("enrichment")) if data.get("enrichment") else None,
            json.dumps(data.get("linkedin")) if data.get("linkedin") else None,
            data.get("notes", ""),
            datetime.utcnow().isoformat(),
            data.get("search_query"),
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def list_saved_founders() -> List[Dict]:
    """Return all saved founders, newest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM saved_founders ORDER BY saved_at DESC"
    ).fetchall()
    conn.close()
    results = []
    for row in rows:
        d = dict(row)
        for json_field in ("product_eval", "card", "enrichment", "linkedin"):
            if d.get(json_field):
                try:
                    d[json_field] = json.loads(d[json_field])
                except (json.JSONDecodeError, TypeError):
                    pass
        results.append(d)
    return results


def get_saved_founder(founder_id: int) -> Optional[Dict]:
    """Get a single saved founder by ID."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM saved_founders WHERE id = ?", (founder_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for json_field in ("product_eval", "card", "enrichment", "linkedin"):
        if d.get(json_field):
            try:
                d[json_field] = json.loads(d[json_field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def update_founder_notes(founder_id: int, notes: str) -> bool:
    """Update notes for a saved founder."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE saved_founders SET notes = ? WHERE id = ?",
        (notes, founder_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def delete_saved_founder(founder_id: int) -> bool:
    """Delete a saved founder. Returns True if deleted."""
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM saved_founders WHERE id = ?", (founder_id,)
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def is_founder_saved(name: str, company: Optional[str] = None) -> Optional[int]:
    """Check if a founder is already saved. Returns the id or None."""
    conn = _get_conn()
    if company:
        row = conn.execute(
            "SELECT id FROM saved_founders WHERE LOWER(name) = LOWER(?) AND LOWER(company) = LOWER(?)",
            (name, company),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM saved_founders WHERE LOWER(name) = LOWER(?) AND company IS NULL",
            (name,),
        ).fetchone()
    conn.close()
    return row["id"] if row else None


def export_csv() -> str:
    """Export all saved founders as CSV string."""
    founders = list_saved_founders()
    if not founders:
        return ""

    output = io.StringIO()
    fields = [
        "id", "name", "company", "role", "industry", "stage",
        "date_founded", "product", "product_desc", "source", "url",
        "overall_score", "notes", "saved_at",
        "product_score", "market_potential", "innovation_signal",
        "scalability", "product_stage", "verdict",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for f in founders:
        row = {k: f.get(k, "") for k in fields}
        # Flatten product_eval fields
        pe = f.get("product_eval")
        if isinstance(pe, dict):
            row["product_score"] = pe.get("product_score", "")
            row["market_potential"] = pe.get("market_potential", "")
            row["innovation_signal"] = pe.get("innovation_signal", "")
            row["scalability"] = pe.get("scalability", "")
            row["product_stage"] = pe.get("product_stage", "")
            row["verdict"] = pe.get("verdict", "")
        writer.writerow(row)

    return output.getvalue()


def export_json() -> List[Dict]:
    """Export all saved founders as JSON-serializable list."""
    return list_saved_founders()


# Initialize database on import
init_db()
