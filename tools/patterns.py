from .db import execute_query, execute_returning
from typing import Any
import json

def get_master_patterns() -> str:
    """Fetch the latest master pattern file."""
    rows = execute_query("""
        SELECT patterns_text, version, last_updated
        FROM master_patterns
        ORDER BY version DESC
        LIMIT 1
    """)
    if not rows:
        return "No patterns learned yet. System is in early learning phase."
    row = rows[0]
    return f"# Master Patterns (v{row['version']}, updated {row['last_updated'].date()})\n\n{row['patterns_text']}"


def get_seasonal_baseline(season: str) -> str:
    """Get seasonal baseline for a specific season e.g. 'Winter 2026'."""
    rows = execute_query("""
        SELECT summary_text, key_thresholds, next_season_focus
        FROM seasonal_summaries
        WHERE season = %s
    """, (season,))
    if not rows:
        return f"No baseline found for {season}. This season has not been summarised yet."
    row = rows[0]
    thresholds = json.dumps(row['key_thresholds'], indent=2) if row['key_thresholds'] else "None recorded"
    focus = ", ".join(row['next_season_focus']) if row['next_season_focus'] else "None recorded"
    return f"""## {season} Baseline

{row['summary_text']}

### Key Thresholds
{thresholds}

### Focus for Next {season}
{focus}"""


def store_master_patterns(patterns_text: str, word_count: int, data_sources: list[str]) -> str:
    """Store a new master patterns version, keeping only latest 2."""
    row = execute_returning("""
        INSERT INTO master_patterns (version, patterns_text, word_count, last_updated, data_source)
        VALUES (
            (SELECT COALESCE(MAX(version), 0) + 1 FROM master_patterns),
            %s, %s, NOW(), %s
        )
        RETURNING id, version
    """, (patterns_text, word_count, json.dumps({"sources": data_sources})))

    if row is None:
        raise RuntimeError("INSERT into master_patterns returned no row")

    # Prune to latest 2 versions
    execute_query("""
        DELETE FROM master_patterns
        WHERE id NOT IN (
            SELECT id FROM master_patterns
            ORDER BY version DESC
            LIMIT 2
        )
    """, fetch=False)

    return f"Master patterns stored as version {row['version']}."


def store_seasonal_summary(season: str, summary_text: str, key_thresholds: dict[str, Any], next_season_focus: list[str]) -> str:
    """Store or update a seasonal summary."""
    execute_query("""
        INSERT INTO seasonal_summaries (season, summary_text, key_thresholds, next_season_focus, created_at, quarter_end_date)
        VALUES (%s, %s, %s, %s, NOW(), CURRENT_DATE)
        ON CONFLICT (season) DO UPDATE SET
            summary_text = EXCLUDED.summary_text,
            key_thresholds = EXCLUDED.key_thresholds,
            next_season_focus = EXCLUDED.next_season_focus,
            created_at = NOW()
    """, (season, summary_text, json.dumps(key_thresholds), json.dumps(next_season_focus)), fetch=False)
    return f"Seasonal summary for {season} stored."


def get_all_seasonal_summaries() -> str:
    """Fetch all seasonal summaries for master pattern synthesis."""
    rows = execute_query("""
        SELECT season, summary_text, key_thresholds, created_at
        FROM seasonal_summaries
        ORDER BY created_at DESC
    """)
    if not rows:
        return "No seasonal summaries yet."
    result = "# All Seasonal Summaries\n\n"
    for row in rows:
        result += f"## {row['season']}\n{row['summary_text']}\n\n"
    return result