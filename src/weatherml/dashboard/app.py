"""Read-only dashboard for the WeatherML API.

Run with:

    uv run python -m weatherml.dashboard.app

It talks only to the FastAPI service (`DASHBOARD_API_BASE_URL`, default
http://localhost:8811), which in turn reads from Postgres. Nothing in this
module calls weatherstack, so refreshing or polling this dashboard never
touches your weatherstack quota — only Airflow's `ingest_weather` DAG does
that, on `INGESTION_POLL_INTERVAL_MINUTES`.
"""

from __future__ import annotations

from datetime import datetime

import dash_ag_grid as dag
import dash_mantine_components as dmc
import plotly.graph_objects as go
import requests
from dash import Dash, Input, Output, dcc, html

from weatherml.config import get_settings
from weatherml.dashboard import api_client, insights

HORIZONS_HOURS = (1, 3)
HISTORY_LIMIT = 288  # 24h of 5-minute observations

app = Dash(__name__, title="WeatherML Dashboard")

GRID_COLUMN_DEFS = [
    {"field": "observation_time", "headerName": "Time", "sort": "desc", "minWidth": 190},
    {"field": "temperature_c", "headerName": "Temp (°C)", "type": "numericColumn"},
    {"field": "feelslike_c", "headerName": "Feels like (°C)", "type": "numericColumn"},
    {"field": "humidity_pct", "headerName": "Humidity (%)", "type": "numericColumn"},
    {"field": "pressure_hpa", "headerName": "Pressure (hPa)", "type": "numericColumn"},
    {"field": "wind_speed_kph", "headerName": "Wind (km/h)", "type": "numericColumn"},
    {"field": "precip_mm", "headerName": "Precip (mm)", "type": "numericColumn"},
    {"field": "weather_description", "headerName": "Conditions", "minWidth": 160},
    {"field": "heat_index_c", "headerName": "Heat index (°C)", "type": "numericColumn"},
    {"field": "dew_point_c", "headerName": "Dew point (°C)", "type": "numericColumn"},
    {"field": "wind_chill_c", "headerName": "Wind chill (°C)", "type": "numericColumn"},
    {"field": "temp_rate_of_change_1h", "headerName": "Δ Temp 1h (°C)", "type": "numericColumn"},
    {"field": "pressure_trend_3h", "headerName": "Pressure trend (hPa/h)", "type": "numericColumn"},
    {"field": "storm_risk", "headerName": "Storm risk", "minWidth": 120},
]

GRID_DEFAULT_COL_DEF = {"sortable": True, "filter": True, "resizable": True, "minWidth": 110}


def _fmt(value: float | int | None, unit: str = "", ndigits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{round(value, ndigits)}{unit}"


def _stat_card(label: str, value: str, color: str = "blue") -> dmc.Card:
    return dmc.Card(
        withBorder=True,
        radius="md",
        padding="md",
        children=[
            dmc.Text(label, size="sm", c="dimmed"),
            dmc.Text(value, size="xl", fw=700, c=color),
        ],
    )


def build_conditions(latest: dict | None) -> list:
    if latest is None:
        return [dmc.Alert("No observations ingested for this location yet.", color="yellow")]

    obs_time = latest["observation_time"]
    return [
        dmc.Text(f"As of {obs_time}", size="sm", c="dimmed"),
        dmc.SimpleGrid(
            cols={"base": 2, "sm": 4},
            children=[
                _stat_card("Temperature", _fmt(latest["temperature_c"], "°C")),
                _stat_card("Feels like", _fmt(latest["feelslike_c"], "°C")),
                _stat_card("Humidity", _fmt(latest["humidity_pct"], "%", ndigits=0)),
                _stat_card("Pressure", _fmt(latest["pressure_hpa"], " hPa", ndigits=0)),
                _stat_card("Wind", _fmt(latest["wind_speed_kph"], " km/h")),
                _stat_card("Precipitation", _fmt(latest["precip_mm"], " mm")),
                _stat_card("Conditions", latest["weather_description"] or "—"),
                _stat_card("Daylight", "Day" if latest["is_day"] else "Night"),
            ],
        ),
    ]


def build_predictions(preds: dict[int, dict | None]) -> list:
    cards = []
    for horizon in HORIZONS_HOURS:
        pred = preds.get(horizon)
        if pred is None:
            cards.append(
                dmc.Card(
                    withBorder=True,
                    radius="md",
                    padding="md",
                    children=[
                        dmc.Text(f"+{horizon}h forecast", size="sm", c="dimmed"),
                        dmc.Text("no production model / no data yet", size="sm", c="red"),
                    ],
                )
            )
            continue
        cards.append(
            dmc.Card(
                withBorder=True,
                radius="md",
                padding="md",
                children=[
                    dmc.Text(f"+{horizon}h forecast", size="sm", c="dimmed"),
                    dmc.Text(_fmt(pred["predicted_temp_c"], "°C"), size="xl", fw=700, c="grape"),
                    dmc.Text(
                        f"{pred['model_name']} v{pred['model_version']} ({pred['model_alias']})",
                        size="xs",
                        c="dimmed",
                    ),
                ],
            )
        )
    return dmc.SimpleGrid(cols={"base": 1, "sm": len(HORIZONS_HOURS)}, children=cards)


def build_history_figure(history: list[dict]) -> go.Figure:
    fig = go.Figure()
    rows = sorted(history, key=lambda r: r["observation_time"])
    times = [datetime.fromisoformat(r["observation_time"]) for r in rows]

    fig.add_trace(
        go.Scatter(
            x=times,
            y=[r["temperature_c"] for r in rows],
            mode="lines",
            name="Temperature (°C)",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=times,
            y=[r["feelslike_c"] for r in rows],
            mode="lines",
            name="Feels like (°C)",
            line={"dash": "dot"},
        )
    )
    fig.update_layout(
        template="plotly_white",
        margin={"l": 40, "r": 20, "t": 20, "b": 40},
        height=320,
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
    )
    return fig


def build_insight_summary(enriched_rows: list[dict]) -> list:
    if not enriched_rows:
        return [dmc.Text("No observations in this window yet.", size="sm", c="dimmed")]

    temps = [r["temperature_c"] for r in enriched_rows if r["temperature_c"] is not None]
    heat_indices = [r["heat_index_c"] for r in enriched_rows if r["heat_index_c"] is not None]
    wind_chills = [r["wind_chill_c"] for r in enriched_rows if r["wind_chill_c"] is not None]
    storm_rows = [r for r in enriched_rows if r["storm_risk"]]

    return dmc.SimpleGrid(
        cols={"base": 2, "sm": 4},
        children=[
            _stat_card("Rows in window", str(len(enriched_rows))),
            _stat_card(
                "Avg temp (window)",
                _fmt(sum(temps) / len(temps), "°C") if temps else "—",
            ),
            _stat_card(
                "Max heat index",
                _fmt(max(heat_indices), "°C") if heat_indices else "—",
                color="orange",
            ),
            _stat_card(
                "Min wind chill",
                _fmt(min(wind_chills), "°C") if wind_chills else "—",
                color="cyan",
            ),
            _stat_card(
                "Storm-risk readings",
                str(len(storm_rows)),
                color="red" if storm_rows else "blue",
            ),
        ],
    )


def serve_layout():
    settings = get_settings()
    try:
        locations = api_client.get_locations()
        api_error = None
    except requests.RequestException as exc:
        locations = []
        api_error = f"Could not reach the WeatherML API at {settings.dashboard_api_base_url}: {exc}"

    location_options = [
        {"value": str(loc["location_id"]), "label": loc["display_name"]} for loc in locations
    ]
    default_value = location_options[0]["value"] if location_options else None

    return dmc.MantineProvider(
        [
            dmc.Container(
                size="lg",
                py="lg",
                children=[
                    dmc.Group(
                        justify="space-between",
                        children=[
                            dmc.Title("WeatherML Dashboard", order=2),
                            dmc.Badge("reads from Postgres via the API only", color="teal"),
                        ],
                    ),
                    dmc.Space(h=10),
                    dmc.Alert(
                        api_error,
                        color="red",
                        title="API unreachable",
                        style={"display": "block" if api_error else "none"},
                        id="startup-error-alert",
                    ),
                    dmc.Select(
                        id="location-select",
                        label="Location",
                        data=location_options,
                        value=default_value,
                        w=300,
                    ),
                    dcc.Interval(
                        id="refresh-interval",
                        interval=settings.dashboard_refresh_seconds * 1000,
                        n_intervals=0,
                    ),
                    dmc.Space(h=20),
                    dmc.Alert(
                        id="error-alert",
                        color="red",
                        title="API error",
                        style={"display": "none"},
                    ),
                    dmc.Title("Current conditions", order=4),
                    html.Div(id="current-conditions"),
                    dmc.Space(h=20),
                    dmc.Title("Forecast", order=4),
                    html.Div(id="predictions-row"),
                    dmc.Space(h=20),
                    dmc.Title("Last 24h", order=4),
                    dcc.Graph(id="temp-history-graph"),
                    dmc.Space(h=20),
                    dmc.Group(
                        justify="space-between",
                        children=[
                            dmc.Title("Data insights", order=4),
                            dmc.Button(
                                "Export CSV",
                                id="export-csv-button",
                                size="xs",
                                variant="light",
                            ),
                        ],
                    ),
                    dmc.Text(
                        "Heat index, dew point, wind chill, pressure trend and storm risk — "
                        "computed with the same functions in "
                        "weatherml.features.functions used to build model training features, "
                        "applied here to whatever history is loaded above.",
                        size="xs",
                        c="dimmed",
                    ),
                    dmc.Space(h=10),
                    html.Div(id="insight-summary"),
                    dmc.Space(h=10),
                    dag.AgGrid(
                        id="observations-grid",
                        columnDefs=GRID_COLUMN_DEFS,
                        defaultColDef=GRID_DEFAULT_COL_DEF,
                        rowData=[],
                        columnSize="responsiveSizeToFit",
                        style={"height": 420},
                        csvExportParams={"fileName": "weatherml_observations.csv"},
                    ),
                    dmc.Space(h=20),
                    dmc.Text(
                        "Ingestion runs on Airflow's own schedule "
                        "(INGESTION_POLL_INTERVAL_MINUTES) — this page only queries "
                        "already-ingested data, so leaving it open does not use "
                        "weatherstack quota.",
                        size="xs",
                        c="dimmed",
                    ),
                ],
            )
        ]
    )


app.layout = serve_layout


@app.callback(
    Output("current-conditions", "children"),
    Output("predictions-row", "children"),
    Output("temp-history-graph", "figure"),
    Output("insight-summary", "children"),
    Output("observations-grid", "rowData"),
    Output("error-alert", "children"),
    Output("error-alert", "style"),
    Input("location-select", "value"),
    Input("refresh-interval", "n_intervals"),
)
def refresh(location_id: str | None, _n_intervals: int):
    empty_fig = go.Figure()
    if location_id is None:
        return [], [], empty_fig, [], [], "Select a location.", {"display": "block"}

    loc_id = int(location_id)
    try:
        latest = api_client.get_latest_observation(loc_id)
        history = api_client.get_observation_history(loc_id, limit=HISTORY_LIMIT)
        preds = {h: api_client.predict(loc_id, h) for h in HORIZONS_HOURS}
    except requests.RequestException as exc:
        error = f"Could not reach the WeatherML API: {exc}"
        return [], [], empty_fig, [], [], error, {"display": "block"}

    enriched = insights.enrich_observations(history) if history else []

    return (
        build_conditions(latest),
        build_predictions(preds),
        build_history_figure(history) if history else empty_fig,
        build_insight_summary(enriched),
        enriched,
        "",
        {"display": "none"},
    )


@app.callback(
    Output("observations-grid", "exportDataAsCsv"),
    Input("export-csv-button", "n_clicks"),
    prevent_initial_call=True,
)
def export_csv(_n_clicks):
    return True


def main() -> None:
    settings = get_settings()
    app.run(host="0.0.0.0", port=settings.dashboard_port, debug=False)


if __name__ == "__main__":
    main()
