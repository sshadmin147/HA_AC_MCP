import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

from tools.db import execute_query
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
    get_this_week_summary,
    get_recent_weekly_summaries,
    store_weekly_summary,
    get_weekly_aggregates_for_summary,
    get_weekly_decisions_by_timeblock
)

app = FastAPI(title="AC Context Brain", version="1.0.0")
_NZ = ZoneInfo("Pacific/Auckland")

# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------

def _nz_ts(dt: datetime | None) -> str:
    """Format a datetime as NZT, gracefully handling naive (UTC) and aware timestamps."""
    if dt is None:
        return '?'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    nz = dt.astimezone(_NZ)
    return nz.strftime(f'%a %d %b, %H:%M {nz.strftime("%Z")}')

def _raw_decisions(count: int) -> list[dict[str, Any]]:
    rows = execute_query("""
        SELECT id, timestamp, ac_mode, fan_speed, duration_minutes,
               indoor_temp_before, indoor_temp_after, outdoor_temp,
               wind_speed, humidity, power_price, is_free_power,
               reached_target, overshot, overshot_by, ai_reasoning
        FROM ac_decisions
        ORDER BY timestamp DESC
        LIMIT %s
    """, (count,))
    return [dict(r) for r in rows]


def _stat_card(label: str, value: str, sub: str = "", color: str = "text-white") -> str:
    sub_html = f'<p class="text-xs text-slate-500 mt-0.5">{sub}</p>' if sub else ""
    return f"""
<div class="bg-slate-800 rounded-2xl p-4 border border-slate-700">
  <p class="text-slate-400 text-xs font-medium uppercase tracking-wider mb-1">{label}</p>
  <p class="text-2xl font-bold {color} leading-none">{value}</p>
  {sub_html}
</div>"""


def _decision_card(d: dict[str, Any]) -> str:
    ts = _nz_ts(d['timestamp'])

    if d['ac_mode'] == 'heat':
        mode_col, mode_icon = "text-orange-400", "🔥"
    else:
        mode_col, mode_icon = "text-blue-400", "❄️"

    t_before = f"{d['indoor_temp_before']:.1f}°C" if d['indoor_temp_before'] is not None else "?"
    t_after  = f"{d['indoor_temp_after']:.1f}°C"  if d['indoor_temp_after']  is not None else "—"

    if d['reached_target'] is True:
        badge = '<span class="px-2 py-0.5 rounded-full text-xs bg-green-900/60 text-green-300 font-medium">✓ Reached</span>'
    elif d['reached_target'] is False:
        badge = '<span class="px-2 py-0.5 rounded-full text-xs bg-red-900/60 text-red-300 font-medium">✗ Missed</span>'
    else:
        badge = '<span class="px-2 py-0.5 rounded-full text-xs bg-amber-900/60 text-amber-300 font-medium">⏳ Pending</span>'

    delta_html = ""
    if d['indoor_temp_after'] is not None and d['indoor_temp_before'] is not None:
        delta = d['indoor_temp_after'] - d['indoor_temp_before']
        col = "text-orange-400" if delta > 0 else "text-blue-400"
        delta_html = f' <span class="{col} text-xs">({delta:+.1f}°C)</span>'

    overshoot_html = ""
    if d['overshot'] and d['overshot_by']:
        overshoot_html = f'<span class="text-xs text-red-400 ml-1">+{d["overshot_by"]:.1f}°C over</span>'

    reasoning_html = ""
    if isinstance(d.get('ai_reasoning'), dict):
        r = d['ai_reasoning'].get('reasoning', '')
        if r:
            short = r[:280] + ("…" if len(r) > 280 else "")
            reasoning_html = f'<p class="mt-3 text-xs text-slate-400 italic leading-relaxed">{short}</p>'

    if d['is_free_power']:
        price_html = '<span class="text-emerald-400 text-xs font-medium">⚡ Free power</span>'
    elif d['power_price'] is not None:
        price_html = f'<span class="text-slate-400 text-xs">${d["power_price"]:.4f}/kWh</span>'
    else:
        price_html = ""

    outdoor = f"{d['outdoor_temp']:.1f}°C" if d['outdoor_temp'] is not None else "?"
    humidity = f"{d['humidity']:.0f}%"      if d['humidity']    is not None else "?"
    wind     = f"{d['wind_speed']:.0f} km/h" if d['wind_speed']  is not None else "?"

    return f"""
<div class="bg-slate-800 rounded-2xl p-4 border border-slate-700">
  <div class="flex items-start justify-between gap-2 mb-3">
    <div>
      <p class="text-slate-300 text-sm font-medium">{ts}</p>
      <p class="text-slate-500 text-xs">#{d['id']}</p>
    </div>
    {badge}
  </div>
  <div class="flex flex-wrap items-center gap-x-4 gap-y-1 mb-3">
    <span class="{mode_col} font-semibold">{mode_icon} {d['ac_mode'].upper()}</span>
    <span class="text-slate-300 text-sm">Fan <span class="text-white font-mono">{d['fan_speed']}</span></span>
    <span class="text-slate-300 text-sm">{d['duration_minutes']} min</span>
    {price_html}
  </div>
  <div class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
    <div>
      <p class="text-slate-500 text-xs">Indoor</p>
      <p class="text-white font-mono">{t_before} → {t_after}{delta_html}{overshoot_html}</p>
    </div>
    <div>
      <p class="text-slate-500 text-xs">Outdoor</p>
      <p class="text-white font-mono">{outdoor}</p>
    </div>
    <div>
      <p class="text-slate-500 text-xs">Humidity</p>
      <p class="text-white font-mono">{humidity}</p>
    </div>
    <div>
      <p class="text-slate-500 text-xs">Wind</p>
      <p class="text-white font-mono">{wind}</p>
    </div>
  </div>
  {reasoning_html}
</div>"""


def _count_pills(current: int) -> str:
    pills = []
    for n in (2, 5, 10, 20):
        cls = "bg-blue-600 text-white" if current == n else "bg-slate-700 text-slate-300 hover:bg-slate-600"
        pills.append(f'<a href="/?count={n}" class="px-3 py-1 rounded-full text-xs font-medium {cls}">{n}</a>')
    return "".join(pills)


def _build_dashboard(count: int) -> str:
    decisions  = _raw_decisions(count)
    stats      = get_weekly_aggregates_for_summary()
    pending    = get_pending_outcomes()
    week_text  = get_this_week_summary()
    weekly_cl  = get_recent_weekly_summaries(1)
    seasonal   = get_all_seasonal_summaries()
    patterns   = get_master_patterns()

    # --- stats ---
    total    = int(stats.get('total_decisions') or 0)
    heat     = int(stats.get('heat_count')      or 0)
    cool     = int(stats.get('cool_count')      or 0)
    success  = stats.get('success_rate')
    ovshoot  = stats.get('overshoot_rate')
    avg_d    = stats.get('avg_delta')
    tmin     = stats.get('temp_min')
    tmax     = stats.get('temp_max')
    free_m   = int(stats.get('free_power_minutes') or 0)
    paid     = float(stats.get('total_paid_cost')  or 0)

    s_val    = f"{success:.1f}%"   if success  is not None else "N/A"
    ov_val   = f"{ovshoot:.1f}%"   if ovshoot  is not None else "N/A"
    d_val    = f"{avg_d:+.2f}°C"  if avg_d    is not None else "N/A"
    r_val    = f"{tmin:.1f}–{tmax:.1f}°C" if tmin is not None and tmax is not None else "N/A"
    s_col    = "text-green-400"  if success  and success  > 80 else ("text-amber-400"  if success  else "text-slate-400")
    ov_col   = "text-red-400"    if ovshoot  and ovshoot  > 20 else ("text-green-400"  if ovshoot is not None else "text-slate-400")

    # --- pending outcomes alert ---
    pending_html = ""
    if pending:
        items = "".join(
            f'<li class="text-amber-300 text-sm">Decision #{p["decision_id"]} — due {p["scheduled_for"].strftime("%H:%M") if hasattr(p["scheduled_for"], "strftime") else p["scheduled_for"]}</li>'
            for p in pending
        )
        pending_html = f"""
<div class="bg-amber-900/30 border border-amber-700 rounded-2xl p-4 mb-6">
  <p class="text-amber-400 font-semibold text-sm mb-2">⏳ {len(pending)} outcome(s) awaiting recording</p>
  <ul class="space-y-1 list-disc list-inside">{items}</ul>
</div>"""

    # --- decision cards ---
    if decisions:
        cards_html = '\n'.join(_decision_card(d) for d in decisions)
    else:
        cards_html = '<p class="text-slate-500 text-sm">No decisions recorded yet.</p>'

    now = datetime.now().strftime('%d %b %Y, %H:%M')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AC Brain</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body {{ background: #0f172a; color: #e2e8f0; }}
    pre  {{ white-space: pre-wrap; word-break: break-word; font-family: inherit; line-height: 1.65; }}
    details > summary {{ list-style: none; }}
    details > summary::-webkit-details-marker {{ display: none; }}
  </style>
</head>
<body class="min-h-screen px-4 py-6 md:px-8 md:py-10">
<div class="max-w-3xl mx-auto">

  <!-- header -->
  <div class="flex items-center justify-between mb-7">
    <div>
      <h1 class="text-2xl font-bold text-white tracking-tight">AC Brain</h1>
      <p class="text-slate-500 text-xs mt-0.5">{now}</p>
    </div>
    <a href="/?count={count}" class="text-slate-500 hover:text-white text-lg leading-none" title="Refresh">↺</a>
  </div>

  <!-- stats grid: 2-col on mobile, 4-col on md -->
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
    {_stat_card("Decisions (7d)", str(total), f"{heat} heat · {cool} cool")}
    {_stat_card("Success Rate",   s_val,   "reached 20–22°C", s_col)}
    {_stat_card("Overshoot Rate", ov_val,  "above 22°C",      ov_col)}
    {_stat_card("Indoor Range",   r_val,   f"avg delta {d_val}")}
  </div>
  <div class="grid grid-cols-2 gap-3 mb-8">
    {_stat_card("Free Power",   f"{free_m} min", "this week", "text-emerald-400")}
    {_stat_card("Paid Cost",    f"${paid:.2f}",  "this week")}
  </div>

  {pending_html}

  <!-- recent decisions -->
  <div class="mb-8">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-base font-semibold text-white">Recent Decisions</h2>
      <div class="flex gap-1.5">{_count_pills(count)}</div>
    </div>
    <div class="space-y-3">{cards_html}</div>
  </div>

  <!-- this week computed stats -->
  <div class="mb-6">
    <h2 class="text-base font-semibold text-white mb-3">This Week</h2>
    <div class="bg-slate-800 rounded-2xl p-4 border border-slate-700">
      <pre class="text-slate-300 text-sm">{week_text}</pre>
    </div>
  </div>

  <!-- collapsibles -->
  <details class="mb-3 bg-slate-800 rounded-2xl border border-slate-700">
    <summary class="flex items-center justify-between px-4 py-3.5 cursor-pointer select-none">
      <span class="text-slate-200 font-medium text-sm">Weekly Summary (Claude)</span>
      <span class="text-slate-500 text-xs">tap to expand</span>
    </summary>
    <div class="px-4 pb-4 pt-3 border-t border-slate-700">
      <pre class="text-slate-300 text-sm">{weekly_cl}</pre>
    </div>
  </details>

  <details class="mb-3 bg-slate-800 rounded-2xl border border-slate-700">
    <summary class="flex items-center justify-between px-4 py-3.5 cursor-pointer select-none">
      <span class="text-slate-200 font-medium text-sm">Seasonal Summaries</span>
      <span class="text-slate-500 text-xs">tap to expand</span>
    </summary>
    <div class="px-4 pb-4 pt-3 border-t border-slate-700">
      <pre class="text-slate-300 text-sm">{seasonal}</pre>
    </div>
  </details>

  <details class="mb-3 bg-slate-800 rounded-2xl border border-slate-700">
    <summary class="flex items-center justify-between px-4 py-3.5 cursor-pointer select-none">
      <span class="text-slate-200 font-medium text-sm">Master Patterns</span>
      <span class="text-slate-500 text-xs">tap to expand</span>
    </summary>
    <div class="px-4 pb-4 pt-3 border-t border-slate-700">
      <pre class="text-slate-300 text-sm">{patterns}</pre>
    </div>
  </details>

  <p class="text-center text-slate-700 text-xs mt-8 pb-4">AC Brain</p>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Dashboard route
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(count: int = Query(default=2, ge=1, le=100)) -> HTMLResponse:
    return HTMLResponse(_build_dashboard(count))


# ---------------------------------------------------------------------------
# Existing JSON API
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    tool: str
    arguments: dict[str, Any] = {}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/tools")
def list_tools() -> dict[str, list[str]]:
    return {"tools": [
        "get_master_patterns", "get_seasonal_baseline",
        "get_this_week_summary", "get_last_n_decisions",
        "store_decision", "record_outcome", "get_pending_outcomes",
        "get_weekly_aggregates_for_summary", "store_weekly_summary",
        "get_recent_weekly_summaries", "get_weekly_decisions_by_timeblock", "store_seasonal_summary",
        "get_all_seasonal_summaries", "store_master_patterns", "run_cleanup",
    ]}


@app.post("/call")
def call_tool(body: ToolCall) -> dict[str, Any]:
    try:
        name = body.tool
        args = body.arguments

        if name == "get_master_patterns":
            result: Any = get_master_patterns()
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
                wind_chill=args.get("wind_chill"),
            )
        elif name == "record_outcome":
            result = record_outcome(
                decision_id=args["decision_id"],
                indoor_temp_after=args["indoor_temp_after"],
                notes=args.get("notes", ""),
            )
        elif name == "get_pending_outcomes":
            pending = get_pending_outcomes()
            result = pending if pending else "No outcomes pending."
        elif name == "get_weekly_aggregates_for_summary":
            result = get_weekly_aggregates_for_summary()
        elif name == "store_weekly_summary":
            result = store_weekly_summary(
                week_start=args["week_start"],
                week_end=args["week_end"],
                season=args["season"],
                summary_json=args["summary_json"],
            )
        elif name == "get_weekly_decisions_by_timeblock":
            result = get_weekly_decisions_by_timeblock()

        elif name == "get_recent_weekly_summaries":
            result = get_recent_weekly_summaries(args.get("count", 4))
        elif name == "store_seasonal_summary":
            result = store_seasonal_summary(
                season=args["season"],
                summary_text=args["summary_text"],
                key_thresholds=args["key_thresholds"],
                next_season_focus=args["next_season_focus"],
            )
        elif name == "get_all_seasonal_summaries":
            result = get_all_seasonal_summaries()
        elif name == "store_master_patterns":
            result = store_master_patterns(
                patterns_text=args["patterns_text"],
                word_count=args["word_count"],
                data_sources=args["data_sources"],
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


if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "5120"))
    uvicorn.run(app, host="0.0.0.0", port=port)
