import asyncio
import os
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import json

from tools.decisions import (
    store_decision,
    get_last_n_decisions,
    record_outcome,
    get_pending_outcomes,
    run_cleanup
)
from tools.patterns import (
    get_master_patterns,
    get_seasonal_baseline,
    store_master_patterns,
    store_seasonal_summary,
    get_all_seasonal_summaries
)
from tools.summaries import (
    get_this_week_summary,
    get_recent_weekly_summaries,
    store_weekly_summary,
    get_weekly_aggregates_for_summary
)

load_dotenv()

app = Server("ac-context-brain")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_master_patterns",
            description="Fetch the latest master pattern file synthesised from all historical learning. Call this at the start of every AC decision.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="get_seasonal_baseline",
            description="Get the stored baseline for a specific season e.g. 'Winter 2026', 'Summer 2025'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "season": {"type": "string", "description": "Season name e.g. 'Winter 2026'"}
                },
                "required": ["season"]
            }
        ),
        Tool(
            name="get_this_week_summary",
            description="Get current week's AC performance stats: success rate, overshoot rate, temp deltas, mode distribution.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="get_last_n_decisions",
            description="Fetch the last N AC decisions with their outcomes. Use to understand recent context before deciding.",
            inputSchema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of decisions to fetch (default 2, max 10)", "default": 2}
                },
                "required": []
            }
        ),
        Tool(
            name="store_decision",
            description="Store an AC decision immediately after Claude decides. Always call this after every decision.",
            inputSchema={
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string", "description": "ISO 8601 timestamp of decision"},
                    "ac_mode": {"type": "string", "enum": ["heat", "cool"]},
                    "fan_speed": {"type": "string", "enum": ["HIGH", "MED", "LOW", "AUTO", "off"]},
                    "duration_minutes": {"type": "integer", "description": "Authorized run time in minutes (1-60)"},
                    "indoor_temp_before": {"type": "number"},
                    "outdoor_temp": {"type": "number"},
                    "wind_speed": {"type": "number"},
                    "solar_radiation": {"type": "number"},
                    "humidity": {"type": "number"},
                    "dewpoint": {"type": "number"},
                    "power_price": {"type": "number"},
                    "is_free_power": {"type": "boolean"},
                    "reasoning": {"type": "string", "description": "The reasoning field from your decision JSON"},
                    "wind_chill": {"type": "number"}
                },
                "required": [
                    "timestamp", "ac_mode", "fan_speed", "duration_minutes",
                    "indoor_temp_before", "outdoor_temp", "wind_speed",
                    "solar_radiation", "humidity", "dewpoint",
                    "power_price", "is_free_power", "reasoning"
                ]
            }
        ),
        Tool(
            name="record_outcome",
            description="Record the outcome of a decision 35+ minutes after it was made.",
            inputSchema={
                "type": "object",
                "properties": {
                    "decision_id": {"type": "integer"},
                    "indoor_temp_after": {"type": "number"},
                    "notes": {"type": "string", "description": "Optional notes about the outcome"}
                },
                "required": ["decision_id", "indoor_temp_after"]
            }
        ),
        Tool(
            name="get_pending_outcomes",
            description="Get list of decisions that are due for outcome recording.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="get_weekly_aggregates_for_summary",
            description="Get raw aggregated stats for the past 7 days to feed into the weekly summarisation workflow.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="store_weekly_summary",
            description="Store a weekly summary generated by Claude.",
            inputSchema={
                "type": "object",
                "properties": {
                    "week_start": {"type": "string", "description": "ISO date e.g. '2026-06-12'"},
                    "week_end": {"type": "string", "description": "ISO date e.g. '2026-06-19'"},
                    "season": {"type": "string", "description": "e.g. 'Winter'"},
                    "summary_json": {"type": "object", "description": "Claude's summary JSON"}
                },
                "required": ["week_start", "week_end", "season", "summary_json"]
            }
        ),
        Tool(
            name="get_recent_weekly_summaries",
            description="Fetch last N weekly summaries for seasonal/master pattern synthesis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "default": 4}
                },
                "required": []
            }
        ),
        Tool(
            name="store_seasonal_summary",
            description="Store a seasonal summary generated by Claude.",
            inputSchema={
                "type": "object",
                "properties": {
                    "season": {"type": "string", "description": "e.g. 'Winter 2026'"},
                    "summary_text": {"type": "string"},
                    "key_thresholds": {"type": "object"},
                    "next_season_focus": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["season", "summary_text", "key_thresholds", "next_season_focus"]
            }
        ),
        Tool(
            name="get_all_seasonal_summaries",
            description="Fetch all seasonal summaries ever stored, for master pattern synthesis.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="store_master_patterns",
            description="Store a newly synthesised master pattern file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "patterns_text": {"type": "string", "description": "The master pattern prose (500 words max)"},
                    "word_count": {"type": "integer"},
                    "data_sources": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["patterns_text", "word_count", "data_sources"]
            }
        ),
        Tool(
            name="run_cleanup",
            description="Delete raw decisions older than 30 days and stale queue entries. Run weekly.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="get_weekly_decisions_by_timeblock",
            description="Get this week's decisions broken into 4-hour blocks and hourly daytime/overnight splits for weekly summary analysis.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "get_master_patterns":
            result = get_master_patterns()

        elif name == "get_seasonal_baseline":
            result = get_seasonal_baseline(arguments["season"])

        elif name == "get_this_week_summary":
            result = get_this_week_summary()

        elif name == "get_last_n_decisions":
            result = get_last_n_decisions(arguments.get("count", 2))

        elif name == "store_decision":
            result = store_decision(
                timestamp=arguments["timestamp"],
                ac_mode=arguments["ac_mode"],
                fan_speed=arguments["fan_speed"],
                duration_minutes=arguments["duration_minutes"],
                indoor_temp_before=arguments["indoor_temp_before"],
                outdoor_temp=arguments["outdoor_temp"],
                wind_speed=arguments["wind_speed"],
                solar_radiation=arguments["solar_radiation"],
                humidity=arguments["humidity"],
                dewpoint=arguments["dewpoint"],
                power_price=arguments["power_price"],
                is_free_power=arguments["is_free_power"],
                reasoning=arguments["reasoning"],
                wind_chill=arguments.get("wind_chill")
            )

        elif name == "record_outcome":
            result = record_outcome(
                decision_id=arguments["decision_id"],
                indoor_temp_after=arguments["indoor_temp_after"],
                notes=arguments.get("notes", "")
            )

        elif name == "get_pending_outcomes":
            pending = get_pending_outcomes()
            if not pending:
                result = "No outcomes pending."
            else:
                result = f"{len(pending)} outcome(s) pending:\n"
                for p in pending:
                    result += f"- Decision #{p['decision_id']} (scheduled {p['scheduled_for']})\n"

        elif name == "get_weekly_aggregates_for_summary":
            data = get_weekly_aggregates_for_summary()
            result = json.dumps(data, indent=2, default=str)

        elif name == "store_weekly_summary":
            result = store_weekly_summary(
                week_start=arguments["week_start"],
                week_end=arguments["week_end"],
                season=arguments["season"],
                summary_json=arguments["summary_json"]
            )

        elif name == "get_recent_weekly_summaries":
            result = get_recent_weekly_summaries(arguments.get("count", 4))

        elif name == "store_seasonal_summary":
            result = store_seasonal_summary(
                season=arguments["season"],
                summary_text=arguments["summary_text"],
                key_thresholds=arguments["key_thresholds"],
                next_season_focus=arguments["next_season_focus"]
            )

        elif name == "get_all_seasonal_summaries":
            result = get_all_seasonal_summaries()

        elif name == "store_master_patterns":
            result = store_master_patterns(
                patterns_text=arguments["patterns_text"],
                word_count=arguments["word_count"],
                data_sources=arguments["data_sources"]
            )

        elif name == "run_cleanup":
            result = run_cleanup()

        elif name == "get_weekly_decisions_by_timeblock":
            from tools.summaries import get_weekly_decisions_by_timeblock
            result = get_weekly_decisions_by_timeblock()

        else:
            result = f"Unknown tool: {name}"

    except Exception as e:
        result = f"Error executing {name}: {str(e)}"

    return [TextContent(type="text", text=result)]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())