from .db import execute_query, execute_returning
import json

def get_this_week_summary() -> str:
    """Compute current week performance stats from raw decisions."""
    rows = execute_query("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN reached_target THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) * 100 as success_rate,
            AVG(indoor_temp_after - indoor_temp_before) as avg_delta,
            SUM(CASE WHEN ac_mode = 'heat' THEN 1 ELSE 0 END) as heat_count,
            SUM(CASE WHEN ac_mode = 'cool' THEN 1 ELSE 0 END) as cool_count,
            SUM(CASE WHEN overshot THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) * 100 as overshoot_rate,
            AVG(duration_minutes) as avg_duration,
            MIN(indoor_temp_before) as temp_min,
            MAX(indoor_temp_before) as temp_max
        FROM ac_decisions
        WHERE timestamp >= NOW() - INTERVAL '7 days'
        AND outcome_recorded_at IS NOT NULL
    """)

    if not rows or rows[0]['total'] == 0:
        return "No completed decisions recorded this week yet."

    r = rows[0]
    success = f"{r['success_rate']:.1f}%" if r['success_rate'] is not None else "N/A"
    delta = f"{r['avg_delta']:.2f}°C" if r['avg_delta'] is not None else "N/A"
    overshoot = f"{r['overshoot_rate']:.1f}%" if r['overshoot_rate'] is not None else "N/A"

    return f"""## This Week's Performance

- Total decisions with outcomes: {r['total']}
- Success rate (reached 20-22°C): {success}
- Average temp delta per decision: {delta}
- Heat decisions: {r['heat_count']} | Cool decisions: {r['cool_count']}
- Overshoot rate: {overshoot}
- Average run time: {r['avg_duration']:.0f} min
- Indoor temp range: {r['temp_min']}°C – {r['temp_max']}°C

Trend: {"Strong" if r['success_rate'] and r['success_rate'] > 85 else "Stable" if r['success_rate'] and r['success_rate'] > 75 else "Needs attention"}"""


def get_recent_weekly_summaries(count: int = 4) -> str:
    """Fetch last N weekly summaries for pattern synthesis."""
    rows = execute_query("""
        SELECT week_start_date, week_end_date, season, summary_json
        FROM weekly_summaries
        ORDER BY week_start_date DESC
        LIMIT %s
    """, (count,))

    if not rows:
        return "No weekly summaries stored yet."

    result = f"# Last {count} Weekly Summaries\n\n"
    for row in rows:
        summary = row['summary_json']
        result += f"## Week of {row['week_start_date']} ({row['season']})\n"
        result += f"{summary.get('week_summary', 'No summary')}\n\n"
        if summary.get('insights'):
            result += "**Key insights:**\n"
            for insight in summary['insights']:
                result += f"- {insight.get('insight', '')}\n"
        result += "\n"
    return result


def store_weekly_summary(week_start: str, week_end: str, season: str, summary_json: dict) -> str:
    """Store a weekly summary."""
    execute_returning("""
        INSERT INTO weekly_summaries (week_start_date, week_end_date, season, summary_json, created_at)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (week_start_date) DO UPDATE SET
            summary_json = EXCLUDED.summary_json,
            created_at = NOW()
    """, (week_start, week_end, season, json.dumps(summary_json)))

    # Cleanup summaries older than 24 months
    execute_query("""
        DELETE FROM weekly_summaries
        WHERE created_at < NOW() - INTERVAL '24 months'
    """, fetch=False)

    return f"Weekly summary for {week_start} to {week_end} stored."


def get_weekly_aggregates_for_summary() -> dict:
    """Get raw aggregates for the past 7 days to feed into Claude weekly summary prompt."""
    rows = execute_query("""
        SELECT
            COUNT(*) as total_decisions,
            SUM(CASE WHEN ac_mode = 'heat' THEN 1 ELSE 0 END) as heat_count,
            SUM(CASE WHEN ac_mode = 'cool' THEN 1 ELSE 0 END) as cool_count,
            SUM(CASE WHEN fan_speed = 'HIGH' THEN 1 ELSE 0 END) as high_count,
            SUM(CASE WHEN fan_speed = 'MED' THEN 1 ELSE 0 END) as med_count,
            SUM(CASE WHEN fan_speed = 'LOW' THEN 1 ELSE 0 END) as low_count,
            SUM(CASE WHEN fan_speed = 'AUTO' THEN 1 ELSE 0 END) as auto_count,
            SUM(CASE WHEN fan_speed = 'off' THEN 1 ELSE 0 END) as off_count,
            SUM(CASE WHEN reached_target THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) * 100 as success_rate,
            AVG(indoor_temp_after - indoor_temp_before) as avg_delta,
            SUM(CASE WHEN overshot THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) * 100 as overshoot_rate,
            AVG(CASE WHEN overshot THEN overshot_by END) as avg_overshoot,
            SUM(CASE WHEN is_free_power = false THEN power_price * duration_minutes / 60.0 ELSE 0 END) as total_paid_cost,
            SUM(CASE WHEN is_free_power = true THEN duration_minutes ELSE 0 END) as free_power_minutes,
            MIN(indoor_temp_before) as temp_min,
            MAX(indoor_temp_before) as temp_max,
            AVG(indoor_temp_before) as temp_avg,
            AVG(duration_minutes) as avg_duration,
            SUM(CASE WHEN wind_speed > 15 THEN 1 ELSE 0 END) as high_wind_decisions,
            SUM(CASE WHEN solar_radiation > 300 THEN 1 ELSE 0 END) as high_solar_decisions,
            SUM(CASE WHEN humidity > 70 THEN 1 ELSE 0 END) as high_humidity_decisions,
            SUM(CASE WHEN dewpoint > 17 THEN 1 ELSE 0 END) as muggy_decisions
        FROM ac_decisions
        WHERE timestamp >= NOW() - INTERVAL '7 days'
        AND outcome_recorded_at IS NOT NULL
    """)
    return dict(rows[0]) if rows else {}