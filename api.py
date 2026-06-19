from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any
import json

from tools.decisions import (
    store_decision, get_last_n_decisions,
    record_outcome, get_pending_outcomes, run_cleanup
)
from tools.patterns import (
    get_master_patterns, get_seasonal_baseline,
    store_master_patterns, store_seasonal_summary,
    get_all_seasonal_summaries
)
from tools.summaries import (
    get_this_week_summary, get_recent_weekly_summaries,
    store_weekly_summary, get_weekly_aggregates_for_summary
)

app = FastAPI(title="AC Context Brain MCP", version="1.0.0")


class ToolCall(BaseModel):
    tool: str
    arguments: dict[str, Any] = {}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/tools")
def list_tools():
    return {"tools": [
        "get_master_patterns",
        "get_seasonal_baseline",
        "get_this_week_summary",
        "get_last_n_decisions",
        "store_decision",
        "record_outcome",
        "get_pending_outcomes",
        "get_weekly_aggregates_for_summary",
        "store_weekly_summary",
        "get_recent_weekly_summaries",
        "store_seasonal_summary",
        "get_all_seasonal_summaries",
        "store_master_patterns",
        "run_cleanup"
    ]}


@app.post("/call")
def call_tool(body: ToolCall):
    try:
        name = body.tool
        args = body.arguments

        if name == "get_master_patterns":
            result = get_master_patterns()

        elif name == "get_seasonal_baseline":
            result = get_seasonal_baseline(args["season"])

        elif name == "get_this_week_summary":
            result = get_this_week_summary()

        elif name == "get_last_n_decisions":
            result = get_last_n_decisions(args.get("count", 2))

        elif name == "store_decision":
            result = store_decision(
                timestamp=args["timestamp"],
                ac_mode=args["ac_mode"],
                fan_speed=args["fan_speed"],
                duration_minutes=args["duration_minutes"],
                indoor_temp_before=args["indoor_temp_before"],
                outdoor_temp=args["outdoor_temp"],
                wind_speed=args["wind_speed"],
                solar_radiation=args["solar_radiation"],
                humidity=args["humidity"],
                dewpoint=args["dewpoint"],
                power_price=args["power_price"],
                is_free_power=args["is_free_power"],
                reasoning=args["reasoning"],
                wind_chill=args.get("wind_chill")
            )

        elif name == "record_outcome":
            result = record_outcome(
                decision_id=args["decision_id"],
                indoor_temp_after=args["indoor_temp_after"],
                notes=args.get("notes", "")
            )

        elif name == "get_pending_outcomes":
            pending = get_pending_outcomes()
            result = f"{len(pending)} pending" if pending else "No outcomes pending."
            if pending:
                result = pending

        elif name == "get_weekly_aggregates_for_summary":
            result = get_weekly_aggregates_for_summary()

        elif name == "store_weekly_summary":
            result = store_weekly_summary(
                week_start=args["week_start"],
                week_end=args["week_end"],
                season=args["season"],
                summary_json=args["summary_json"]
            )

        elif name == "get_recent_weekly_summaries":
            result = get_recent_weekly_summaries(args.get("count", 4))

        elif name == "store_seasonal_summary":
            result = store_seasonal_summary(
                season=args["season"],
                summary_text=args["summary_text"],
                key_thresholds=args["key_thresholds"],
                next_season_focus=args["next_season_focus"]
            )

        elif name == "get_all_seasonal_summaries":
            result = get_all_seasonal_summaries()

        elif name == "store_master_patterns":
            result = store_master_patterns(
                patterns_text=args["patterns_text"],
                word_count=args["word_count"],
                data_sources=args["data_sources"]
            )

        elif name == "run_cleanup":
            result = run_cleanup()

        else:
            raise HTTPException(status_code=404, detail=f"Unknown tool: {name}")

        return {"result": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))