from .db import execute_query
from typing import Any
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


def store_weekly_summary(week_start: str, week_end: str, season: str, summary_json: dict[str, Any]) -> str:
    """Store a weekly summary."""
    execute_query("""
        INSERT INTO weekly_summaries (week_start_date, week_end_date, season, summary_json, created_at)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (week_start_date) DO UPDATE SET
            summary_json = EXCLUDED.summary_json,
            created_at = NOW()
    """, (week_start, week_end, season, json.dumps(summary_json)), fetch=False)

    # Cleanup summaries older than 24 months
    execute_query("""
        DELETE FROM weekly_summaries
        WHERE created_at < NOW() - INTERVAL '24 months'
    """, fetch=False)

    return f"Weekly summary for {week_start} to {week_end} stored."


def get_weekly_aggregates_for_summary() -> dict[str, Any]:
    """Get raw aggregates for the past 7 days to feed into Claude weekly summary prompt."""
    rows = execute_query("""
        SELECT
            COUNT(*) as total_decisions,
            SUM(CASE WHEN ac_mode = 'heat' THEN 1 ELSE 0 END) as heat_count,
            SUM(CASE WHEN ac_mode = 'cool' THEN 1 ELSE 0 END) as cool_count,
            SUM(CASE WHEN fan_speed = 'high' THEN 1 ELSE 0 END) as high_count,
            SUM(CASE WHEN fan_speed = 'medium' THEN 1 ELSE 0 END) as med_count,
            SUM(CASE WHEN fan_speed = 'low' THEN 1 ELSE 0 END) as low_count,
            SUM(CASE WHEN fan_speed = 'auto' THEN 1 ELSE 0 END) as auto_count,
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

def get_weekly_decisions_by_timeblock() -> str:
    """Get this week's decisions broken into daytime (6am-10pm) and overnight (10pm-6am) blocks."""
    rows = execute_query("""
        SELECT
            CASE 
                WHEN EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Pacific/Auckland') >= 22 
                  OR EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Pacific/Auckland') < 6 
                THEN 'overnight'
                ELSE 'daytime'
            END as period,
            EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Pacific/Auckland')::int as hour_nz,
            COUNT(*) as decisions,
            AVG(indoor_temp_before) as avg_temp_before,
            AVG(indoor_temp_after) as avg_temp_after,
            AVG(indoor_temp_after - indoor_temp_before) as avg_delta,
            SUM(CASE WHEN reached_target THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) * 100 as success_rate,
            SUM(CASE WHEN fan_speed = 'high' THEN 1 ELSE 0 END) as high_count,
            SUM(CASE WHEN fan_speed = 'medium' THEN 1 ELSE 0 END) as med_count,
            SUM(CASE WHEN fan_speed = 'low' THEN 1 ELSE 0 END) as low_count,
            SUM(CASE WHEN fan_speed = 'auto' THEN 1 ELSE 0 END) as auto_count,
            SUM(CASE WHEN fan_speed = 'off' THEN 1 ELSE 0 END) as off_count,
            SUM(CASE WHEN is_free_power THEN 1 ELSE 0 END) as free_power_decisions,
            AVG(CASE WHEN is_free_power = false THEN power_price * duration_minutes / 60.0 END) as avg_paid_cost,
            SUM(CASE WHEN overshot THEN 1 ELSE 0 END) as overshoot_count
        FROM ac_decisions
        WHERE timestamp >= NOW() - INTERVAL '7 days'
        AND outcome_recorded_at IS NOT NULL
        GROUP BY period, hour_nz
        ORDER BY period, hour_nz
    """)

    if not rows:
        return "No time-block data available yet."

    # Organise into daytime and overnight blocks
    daytime = [dict(r) for r in rows if r['period'] == 'daytime']
    overnight = [dict(r) for r in rows if r['period'] == 'overnight']

    # Also get 12-hour summary blocks
    blocks = execute_query("""
        SELECT
            CASE
                WHEN EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Pacific/Auckland') >= 6
                 AND EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Pacific/Auckland') < 12 THEN '06:00-12:00 (Morning)'
                WHEN EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Pacific/Auckland') >= 12
                 AND EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Pacific/Auckland') < 18 THEN '12:00-18:00 (Afternoon)'
                WHEN EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Pacific/Auckland') >= 18
                 AND EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Pacific/Auckland') < 22 THEN '18:00-22:00 (Evening)'
                ELSE '22:00-06:00 (Overnight)'
            END as block,
            COUNT(*) as decisions,
            ROUND(AVG(indoor_temp_before)::numeric, 1) as avg_indoor_before,
            ROUND(AVG(indoor_temp_after)::numeric, 1) as avg_indoor_after,
            ROUND((SUM(CASE WHEN reached_target THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) * 100)::numeric, 1) as success_pct,
            SUM(CASE WHEN fan_speed = 'AUTO' THEN 1 ELSE 0 END) as auto_used,
            SUM(CASE WHEN overshot THEN 1 ELSE 0 END) as overshoots,
            ROUND(SUM(CASE WHEN is_free_power = false THEN power_price * duration_minutes / 60.0 ELSE 0 END)::numeric, 3) as paid_cost
        FROM ac_decisions
        WHERE timestamp >= NOW() - INTERVAL '7 days'
        AND outcome_recorded_at IS NOT NULL
        GROUP BY block
        ORDER BY block
    """)

    block_summary = [dict(r) for r in blocks] if blocks else []

    import json
    return json.dumps({
        "four_hour_blocks": block_summary,
        "hourly_daytime": daytime,
        "hourly_overnight": overnight
    }, indent=2, default=str)