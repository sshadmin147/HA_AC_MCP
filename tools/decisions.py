from .db import execute_query, execute_returning
from datetime import datetime, timedelta
from typing import Any
import json

def store_decision(
    timestamp: str,
    ac_mode: str,
    fan_speed: str,
    duration_minutes: int,
    indoor_temp_before: float,
    outdoor_temp: float,
    wind_speed: float,
    solar_radiation: float,
    humidity: float,
    dewpoint: float,
    power_price: float,
    is_free_power: bool,
    reasoning: str,
    wind_chill: float | None = None
) -> str:
    """Store an AC decision and queue outcome recording for 35 minutes later."""
    ts = datetime.fromisoformat(timestamp)
    day_of_week = ts.strftime('%A')
    hour = ts.hour

    row = execute_returning("""
        INSERT INTO ac_decisions (
            timestamp, day_of_week, hour,
            indoor_temp_before, outdoor_temp, wind_speed, wind_chill,
            solar_radiation, humidity, dewpoint,
            power_price, is_free_power,
            ac_mode, fan_speed, duration_minutes,
            ai_reasoning, created_at
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, NOW()
        ) RETURNING id
    """, (
        timestamp, day_of_week, hour,
        indoor_temp_before, outdoor_temp, wind_speed, wind_chill,
        solar_radiation, humidity, dewpoint,
        power_price, is_free_power,
        ac_mode, fan_speed, duration_minutes,
        json.dumps({"reasoning": reasoning})
    ))

    if row is None:
        raise RuntimeError("INSERT into ac_decisions returned no row")
    decision_id = row['id']

    # Schedule outcome recording
    scheduled_for = ts + timedelta(minutes=35)
    execute_returning("""
        INSERT INTO outcome_queue (decision_id, scheduled_for)
        VALUES (%s, %s)
        RETURNING id
    """, (decision_id, scheduled_for))

    return f"Decision #{decision_id} stored. Outcome scheduled for {scheduled_for.strftime('%H:%M')}."


def get_last_n_decisions(count: int = 2) -> str:
    """Fetch last N decisions with outcomes."""
    rows = execute_query("""
        SELECT
            id, timestamp, ac_mode, fan_speed, temperature, duration_minutes,
            indoor_temp_before, indoor_temp_after,
            reached_target, overshot, overshot_by,
            ai_reasoning
        FROM ac_decisions
        ORDER BY timestamp DESC
        LIMIT %s
    """, (count,))
    if not rows:
        return "No decisions recorded yet."
    result = "## Recent Decisions\n\n"
    for row in rows:
        delta: float | None = None
        if row['indoor_temp_after'] is not None and row['indoor_temp_before'] is not None:
            delta = row['indoor_temp_after'] - row['indoor_temp_before']
        status = "✓ REACHED" if row['reached_target'] else ("✗ MISSED" if row['reached_target'] is not None else "⏳ PENDING")
        overshoot_str = f" (overshot {row['overshot_by']:.1f}°C)" if row['overshot'] and row['overshot_by'] else ""
        delta_str = f"{delta:+.2f}°C" if delta is not None else "pending"
        reasoning = row['ai_reasoning'].get('reasoning', 'N/A') if row['ai_reasoning'] else 'N/A'
        temp_str = f"{int(row['temperature'])}°C" if row['temperature'] is not None else "N/A"
        result += f"""### Decision #{row['id']} — {row['timestamp'].strftime('%H:%M on %A')}
- Mode: {row['ac_mode'].upper()} | Fan: {row['fan_speed']} | Temp: {temp_str} | Duration: {row['duration_minutes']}min
- Indoor: {row['indoor_temp_before']}°C → {row['indoor_temp_after'] or '?'}°C (delta: {delta_str})
- Status: {status}{overshoot_str}
- Reasoning: {reasoning}
"""
    return result


def record_outcome(decision_id: int, indoor_temp_after: float, notes: str = "") -> str:
    """Record outcome for a decision 35+ minutes after it was made."""
    rows = execute_query("""
        SELECT indoor_temp_before, timestamp
        FROM ac_decisions WHERE id = %s
    """, (decision_id,))

    if not rows:
        return f"Decision #{decision_id} not found."

    row = rows[0]
    temp_before = row['indoor_temp_before']
    delta = indoor_temp_after - temp_before

    # Comfort range: 20-22°C
    reached_target = 20.0 <= indoor_temp_after <= 22.0
    overshot = indoor_temp_after > 22.0
    overshot_by = round(indoor_temp_after - 22.0, 2) if overshot else None

    time_to_target = (datetime.now(tz=row['timestamp'].tzinfo) - row['timestamp']).total_seconds() / 60

    execute_returning("""
        UPDATE ac_decisions SET
            indoor_temp_after = %s,
            time_to_target_minutes = %s,
            reached_target = %s,
            overshot = %s,
            overshot_by = %s,
            outcome_notes = %s,
            outcome_recorded_at = NOW()
        WHERE id = %s
        RETURNING id
    """, (
        indoor_temp_after,
        round(time_to_target, 1),
        reached_target,
        overshot,
        overshot_by,
        json.dumps({"notes": notes}) if notes else None,
        decision_id
    ))

    # Remove from outcome queue
    execute_query("""
        DELETE FROM outcome_queue WHERE decision_id = %s
    """, (decision_id,), fetch=False)

    status = "✓ REACHED TARGET" if reached_target else "✗ MISSED TARGET"
    overshoot_str = f"\n- Overshot by: {overshot_by}°C" if overshot else ""

    return f"""Outcome recorded for decision #{decision_id}:
- Final temp: {indoor_temp_after}°C (delta: {delta:+.2f}°C)
- Status: {status}{overshoot_str}
- Time elapsed: {time_to_target:.0f} minutes"""


def get_pending_outcomes() -> list[dict[str, Any]]:
    """Get decisions due for outcome recording."""
    rows = execute_query("""
        SELECT oq.id as queue_id, oq.decision_id, oq.scheduled_for,
               ad.indoor_temp_before, ad.ac_mode, ad.fan_speed
        FROM outcome_queue oq
        JOIN ac_decisions ad ON ad.id = oq.decision_id
        WHERE oq.scheduled_for <= NOW()
        ORDER BY oq.scheduled_for ASC
    """)
    return [dict(r) for r in rows] if rows else []


def run_cleanup() -> str:
    """Delete raw decisions older than 30 days and stale queue entries."""
    deleted_count = execute_query("""
        DELETE FROM ac_decisions
        WHERE timestamp < NOW() - INTERVAL '30 days'
    """, fetch=False)

    execute_query("""
        DELETE FROM outcome_queue
        WHERE scheduled_for < NOW() - INTERVAL '2 hours'
        AND decision_id NOT IN (
            SELECT id FROM ac_decisions WHERE outcome_recorded_at IS NULL
        )
    """, fetch=False)

    return f"Cleanup complete. Removed {deleted_count} old decisions."