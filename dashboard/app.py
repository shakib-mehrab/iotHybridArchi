# dashboard/app.py
"""
HybridGuard Operations Dashboard — NiceGUI, port 8090.

Purpose: make the whole system legible at a glance for a live defense — what's
running, which devices are registered, the real pipeline flowing in real time,
the append-only ledger growing, FL trust updating, and all logs — without
narrating terminal by terminal.

Design:
  - Read-only backend. The ONLY action is launching the simulator (via
    dashboard/sim_runner.py), which is exactly what you'd run in a terminal.
  - Two poll cadences, both OFF the UI thread (run.io_bound), so slow WSL peer
    calls never freeze the UI:
        fast  (DASHBOARD_POLL_SECONDS) -> service health, FL status, pipeline, logs
        slow  (FABRIC_POLL_SECONDS)    -> device records + CID history (Fabric)
  - Panels are @ui.refreshable; timers refill a shared `state` then refresh.

Run:  python dashboard/app.py   (or: python -m dashboard.app)
"""

import os
import sys

# Make the project root importable whether launched as a script or a module.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from nicegui import ui, run

from config import settings
from dashboard import services
from dashboard.models import FLStatus, PipelineState
from dashboard.sim_runner import runner


# ── shared snapshot state (filled by timers) ─────────────────────────────────
class State:
    health = []
    fl = FLStatus()
    pipeline = PipelineState()
    logs = {}
    devices = []
    cid_device = settings.DEVICE_IDS[0] if settings.DEVICE_IDS else ""
    cids = []
    last_error = ""


state = State()

GREEN, RED, GREY, AMBER = "#16a34a", "#dc2626", "#9ca3af", "#d97706"


# ── panels ───────────────────────────────────────────────────────────────────
@ui.refreshable
def panel_status():
    up = sum(1 for s in state.health if s.up)
    total = len(state.health)
    with ui.row().classes("items-center gap-2 w-full"):
        ui.label("System Status").classes("text-lg font-bold")
        ui.badge(f"{up}/{total} up", color="green" if up == total else "orange")
    for s in state.health:
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.icon("circle", color=GREEN if s.up else RED).classes("text-xs")
            ui.label(s.name).classes("font-medium w-40")
            ui.label(s.detail or "").classes("text-sm text-gray-500 grow")
            if not s.up:
                with ui.icon("help_outline").classes("text-gray-400 cursor-pointer"):
                    ui.tooltip(f"To activate: {s.hint}")
    if any(not s.up for s in state.health):
        with ui.expansion("How to activate down services", icon="build").classes("w-full mt-1"):
            for s in state.health:
                if not s.up:
                    ui.label(f"• {s.name}: {s.hint}").classes("text-sm text-gray-600")


@ui.refreshable
def panel_pipeline():
    ui.label("Live Pipeline").classes("text-lg font-bold")
    ui.label("Furthest stage reached by the most recent telemetry tick "
             "(from gateway log).").classes("text-xs text-gray-500")
    p = state.pipeline
    labels = services.pipeline_labels()
    with ui.row().classes("items-center gap-1 w-full no-wrap mt-2"):
        for i, name in enumerate(labels):
            reached = i <= p.stage
            failed_here = (not p.ok) and i == p.stage + 1
            color = GREEN if reached else GREY
            if failed_here:
                color = RED
            with ui.column().classes("items-center gap-0"):
                ui.icon("check_circle" if reached else
                        ("cancel" if failed_here else "radio_button_unchecked"),
                        color=color)
                ui.label(name).classes("text-xs").style(f"color:{color}")
            if i < len(labels) - 1:
                ui.icon("chevron_right", color=GREY).classes("text-sm")
    if p.last_device or p.last_line:
        tag = "ANOMALY" if p.anomaly else ("ERROR" if not p.ok else "flowing")
        ui.label(f"{tag} · {p.last_device} · {p.last_line[-70:]}").classes(
            "text-xs text-gray-500 mt-1")


@ui.refreshable
def panel_devices():
    ui.label("Registered Devices").classes("text-lg font-bold")
    if not state.devices:
        ui.label("No device data yet…").classes("text-sm text-gray-500")
        return
    with ui.grid(columns=5).classes("w-full gap-1 items-center"):
        for h in ["Device", "Status", "Trust", "CIDs", "Latest CID"]:
            ui.label(h).classes("text-xs font-bold text-gray-500")
        for d in state.devices:
            reg_color = (GREEN if d.status == "trusted"
                         else RED if d.status == "blacklisted"
                         else AMBER if d.registered else GREY)
            ui.label(d.device_id).classes("text-sm font-medium")
            with ui.row().classes("items-center gap-1 no-wrap"):
                ui.icon("circle", color=reg_color).classes("text-xs")
                lbl = d.status if d.registered else "unregistered"
                if d.excluded:
                    lbl += " (FL-excl)"
                ui.label(lbl).classes("text-sm")
            ui.label("—" if d.trust_score is None else f"{d.trust_score:.2f}").classes("text-sm")
            ui.label(str(d.cid_count)).classes("text-sm")
            ui.label((d.latest_cid[:16] + "…") if d.latest_cid else "—").classes(
                "text-xs text-gray-500")


@ui.refreshable
def panel_fl():
    ui.label("Federated Learning").classes("text-lg font-bold")
    fl = state.fl
    if not fl.reachable:
        ui.label("FL server not reachable").classes("text-sm text-red-500")
        return
    with ui.row().classes("gap-4"):
        ui.label(f"Round: {fl.round}").classes("text-sm")
        ui.label(f"Pending: {len(fl.pending_devices)}").classes("text-sm")
        ui.label(f"Excluded: {len(fl.excluded_devices)}").classes("text-sm")
    if fl.trust_scores:
        for dev, sc in sorted(fl.trust_scores.items()):
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.label(dev).classes("text-xs w-32")
                ui.linear_progress(value=max(0.0, min(1.0, sc)), show_value=False,
                                   size="10px").classes("grow").props(
                    f"color={'red' if sc < 0.3 else 'green'}")
                ui.label(f"{sc:.2f}").classes("text-xs w-10")
    if fl.excluded_devices:
        ui.label("Excluded: " + ", ".join(fl.excluded_devices)).classes(
            "text-xs text-red-500")


@ui.refreshable
def panel_cids():
    with ui.row().classes("items-center gap-2 w-full"):
        ui.label("CID History (append-only ledger)").classes("text-lg font-bold")
        ui.select(settings.DEVICE_IDS, value=state.cid_device,
                  on_change=lambda e: _select_cid_device(e.value)).props("dense outlined").classes("w-48")
    if not state.cids:
        ui.label("No CIDs for this device yet.").classes("text-sm text-gray-500")
        return
    with ui.scroll_area().classes("h-48 w-full"):
        with ui.grid(columns=3).classes("w-full gap-x-4 gap-y-1"):
            for h in ["Timestamp (unix)", "CID", "TxID"]:
                ui.label(h).classes("text-xs font-bold text-gray-500")
            for c in reversed(state.cids):  # newest first
                ui.label(c.timestamp).classes("text-xs")
                ui.label(c.cid_hash).classes("text-xs font-mono")
                ui.label((c.tx_id[:16] + "…") if c.tx_id else "—").classes(
                    "text-xs font-mono text-gray-500")


@ui.refreshable
def panel_logs():
    ui.label("Live Logs").classes("text-lg font-bold")
    with ui.tabs().classes("w-full") as tabs:
        for name in state.logs:
            ui.tab(name)
    default = next(iter(state.logs), None)
    if default is None:
        ui.label("No logs found.").classes("text-sm text-gray-500")
        return
    with ui.tab_panels(tabs, value=default).classes("w-full"):
        for name, lines in state.logs.items():
            with ui.tab_panel(name):
                with ui.scroll_area().classes("h-56 w-full bg-gray-900 rounded"):
                    ui.label("\n".join(lines) if lines else "(empty)").classes(
                        "text-xs font-mono whitespace-pre text-green-300")


@ui.refreshable
def panel_sim():
    ui.label("Simulation Control").classes("text-lg font-bold")
    # ── single run ──
    with ui.row().classes("items-end gap-2 w-full no-wrap"):
        dev = ui.select(settings.DEVICE_IDS, value=settings.DEVICE_IDS[0],
                        label="Device").props("dense outlined").classes("w-40")
        scn = ui.select(settings.SCENARIOS, value=settings.SCENARIOS[0],
                        label="Scenario").props("dense outlined").classes("w-52")
        dur = ui.number("Duration (s)", value=30, min=5, max=3600, step=5).props(
            "dense outlined").classes("w-32")

        def _run_single():
            ok = runner.run_single(dev.value, scn.value, int(dur.value or 30))
            (ui.notify(f"Launched {dev.value} / {scn.value}", type="positive") if ok
             else ui.notify("Already running that device/scenario", type="warning"))
            panel_sim.refresh()

        ui.button("Run", icon="play_arrow", on_click=_run_single).props("color=primary")
    # ── presets ──
    with ui.row().classes("items-center gap-2 w-full mt-1"):
        ui.label("Presets:").classes("text-sm text-gray-500")
        for name in settings.PRESETS:
            def _mk(n):
                def _run():
                    c = runner.run_preset(n)
                    ui.notify(f"{n}: launched {c} device(s)",
                              type="positive" if c else "warning")
                    panel_sim.refresh()
                return _run
            ui.button(name, on_click=_mk(name)).props("outline dense").classes("text-xs")
    # ── running ──
    running = runner.running()
    with ui.row().classes("items-center gap-2 w-full mt-2"):
        ui.label(f"Running: {len(running)}").classes("text-sm font-medium")
        if running:
            ui.button("Stop all", icon="stop", color="red",
                      on_click=lambda: (runner.stop_all(), panel_sim.refresh())).props("dense outline")
    for sp in running:
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.icon("play_circle", color=GREEN).classes("text-sm")
            ui.label(f"{sp.device} · {sp.scenario} · {sp.elapsed}s/{sp.duration}s").classes("text-xs grow")
            ui.button(icon="stop", on_click=lambda k=sp.key: (runner.stop(k), panel_sim.refresh())).props(
                "flat dense round size=sm")


# ── interactions ─────────────────────────────────────────────────────────────
def _select_cid_device(device_id: str):
    state.cid_device = device_id
    # fetch immediately (off-thread) so the panel updates without waiting a cycle

    async def _fetch():
        state.cids = await run.io_bound(services.get_cid_history, device_id)
        panel_cids.refresh()

    ui.timer(0.01, _fetch, once=True)


# ── polling ──────────────────────────────────────────────────────────────────
async def poll_fast():
    try:
        state.health   = await run.io_bound(services.get_service_health)
        state.fl       = await run.io_bound(services.get_fl_status)
        state.pipeline = await run.io_bound(services.get_pipeline_state)
        state.logs     = await run.io_bound(services.get_logs)
        state.last_error = ""
    except Exception as e:
        state.last_error = str(e)
    panel_status.refresh()
    panel_pipeline.refresh()
    panel_fl.refresh()
    panel_logs.refresh()
    panel_sim.refresh()


async def poll_slow():
    try:
        state.devices = await run.io_bound(services.get_devices, state.fl)
        state.cids    = await run.io_bound(services.get_cid_history, state.cid_device)
    except Exception as e:
        state.last_error = str(e)
    panel_devices.refresh()
    panel_cids.refresh()


# ── layout ───────────────────────────────────────────────────────────────────
@ui.page("/")
def index():
    ui.query("body").classes("bg-gray-100")
    with ui.header().classes("items-center justify-between bg-slate-800"):
        ui.label("HybridGuard — Operations Dashboard").classes("text-xl font-bold text-white")
        ui.label(f"poll {settings.DASHBOARD_POLL_SECONDS:g}s / fabric "
                 f"{settings.FABRIC_POLL_SECONDS:g}s").classes("text-xs text-gray-300")

    with ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4"):
        with ui.row().classes("w-full gap-4 no-wrap items-stretch"):
            with ui.card().classes("grow"):
                panel_status()
            with ui.card().classes("grow"):
                panel_pipeline()
        with ui.card().classes("w-full"):
            panel_sim()
        with ui.card().classes("w-full"):
            panel_devices()
        with ui.row().classes("w-full gap-4 no-wrap items-stretch"):
            with ui.card().classes("grow"):
                panel_fl()
            with ui.card().classes("grow"):
                panel_cids()
        with ui.card().classes("w-full"):
            panel_logs()

    # initial fill + recurring timers (per-client)
    ui.timer(0.1, poll_fast, once=True)
    ui.timer(0.1, poll_slow, once=True)
    ui.timer(settings.DASHBOARD_POLL_SECONDS, poll_fast)
    ui.timer(settings.FABRIC_POLL_SECONDS, poll_slow)


ui.run(
    host=settings.SERVICE_HOST,
    port=settings.DASHBOARD_PORT,
    title="HybridGuard Dashboard",
    reload=False,
    show=True,
)
