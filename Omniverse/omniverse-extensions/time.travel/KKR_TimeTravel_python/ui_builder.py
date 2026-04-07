"""Time Travel Extension — UI Builder.

Provides:
- API Settings: URL config + health check
- Backup Timeline: Browse backup timestamps with diff preview
- Stage Restore: Complete restore to backup state + Undo
- M&S Simulation: IoT simulation + real-time capture
- Nucleus: File info display + Reopen from Nucleus
"""

import asyncio
import os
import urllib.parse

import omni.timeline
import omni.ui as ui
import omni.usd
from isaacsim.gui.components.element_wrappers import (
    Button,
    CollapsableFrame,
    StringField,
    TextBlock,
)
from isaacsim.gui.components.ui_utils import get_style

from .api_client import api_get
from .capture_coordinator import CaptureCoordinator, CaptureScope
from .timeline_baker import TimelineBaker
from .restore_engine import (
    capture_undo_snapshot,
    apply_undo_snapshot,
    restore_stage,
)

DEFAULT_API_BASE_URL = os.getenv("LAKEHOUSE_API_URL", "http://localhost:8100")


def _format_session_info(session: dict) -> str:
    """세션의 delta 수와 캡처 시간을 포맷.

    wall-clock 기반 frame 추정은 부정확하므로 (세션 end_time은 마지막 delta
    이후 지연 포함), delta 수와 캡처 시간(초)만 표시한다.
    """
    deltas = session.get("total_deltas", 0)
    start_str = session.get("start_time", "")
    end_str = session.get("end_time", "") or ""
    if start_str and end_str:
        try:
            from datetime import datetime
            start_dt = datetime.fromisoformat(str(start_str))
            end_dt = datetime.fromisoformat(str(end_str))
            duration = (end_dt - start_dt).total_seconds()
            if duration > 0:
                est_frames = int(duration * 60)
                return f"{deltas}d|~{est_frames}f|{duration:.1f}s"
        except (ValueError, TypeError):
            pass
    return f"{deltas}d"


class UIBuilder:
    def __init__(self):
        self.frames = []
        self.wrapped_ui_elements = []
        # State
        self._backup_times_list = []
        self._backup_sources_list = []
        self._selected_backup_idx = 0
        self._backup_page = 0
        self._backup_buttons = []
        self._undo_snapshot = None
        # M&S Capture
        self._coordinator = CaptureCoordinator()
        self._timeline_baker = TimelineBaker()
        self._auto_capture_enabled = False
        self._selected_session_id = None
        self._sessions_cache = []
        self._status_block = None
        self._diff_label = None

    # =========================================================================
    #  Callbacks wired by extension.py
    # =========================================================================

    def on_menu_callback(self):
        pass

    def on_timeline_event(self, event):
        """Timeline PLAY/STOP 이벤트에 따라 Auto Capture 시작/종료."""
        if event.type == int(omni.timeline.TimelineEventType.PLAY):
            self._on_play_started()
        elif event.type == int(omni.timeline.TimelineEventType.STOP):
            self._on_play_stopped()

    def on_stage_event(self, event):
        pass

    def cleanup(self):
        self._coordinator.cleanup()
        if self._timeline_baker.is_replay_active:
            self._timeline_baker.restore_timeline()
        self.wrapped_ui_elements = []

    # =========================================================================
    #  Build UI
    # =========================================================================

    def build_ui(self):
        self._create_status_frame()
        self._create_api_settings_frame()
        self._create_backup_restore_frame()
        self._create_capture_frame()
        self._create_nucleus_frame()

    # ── API Settings Frame ──────────────────────────────────────

    def _create_api_settings_frame(self):
        frame = CollapsableFrame("API Settings", collapsed=True)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                self._api_url_field = StringField(
                    "API URL",
                    default_value=DEFAULT_API_BASE_URL,
                    tooltip="Lakehouse API base URL",
                    read_only=False,
                )
                self.wrapped_ui_elements.append(self._api_url_field)
                with ui.HStack(spacing=5, height=0):
                    ui.Button(
                        "Local (localhost:8100)",
                        height=25,
                        clicked_fn=lambda: self._api_url_field.set_value("http://localhost:8100"),
                        tooltip="Windows / Isaac Sim local dev",
                    )
                    ui.Button(
                        "Docker (lakehouse-api:8000)",
                        height=25,
                        clicked_fn=lambda: self._api_url_field.set_value("http://lakehouse-api:8000"),
                        tooltip="Docker Compose internal network",
                    )
                btn = Button(
                    "Health Check",
                    "TEST CONNECTION",
                    tooltip="Test API connectivity",
                    on_click_fn=self._on_health_check,
                )
                self.wrapped_ui_elements.append(btn)

    def _get_api_url(self) -> str:
        return self._api_url_field.get_value().rstrip("/")

    def _on_health_check(self):
        self._set_status("Checking API connection...")
        asyncio.ensure_future(self._async_health_check())

    async def _async_health_check(self):
        try:
            result = await api_get(self._get_api_url(), "api/v1/health")
            self._set_status(f"[OK] API connected: {result.get('status', 'unknown')}")
        except Exception as e:
            self._set_status(f"[FAIL] Cannot connect to API: {e}")

    # ── Backup Timeline Frame ───────────────────────────────────

    def _create_backup_restore_frame(self):
        """Backup Timeline + Stage Restore — 통합 섹션."""
        frame = CollapsableFrame("Backup & Restore", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Load backup timestamps, select one, and restore.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                # Load button
                btn = Button(
                    "Load Backups",
                    "LOAD BACKUP TIMES",
                    tooltip="Fetch available backup timestamps from API",
                    on_click_fn=self._on_load_backup_times,
                )
                self.wrapped_ui_elements.append(btn)

                # 2x3 backup selection grid
                ui.Label("Backup Times", style={"color": 0xFF999999, "font_size": 11})
                self._backup_buttons = []
                _SELECTED_STYLE = {"Button": {"background_color": 0xFF2266AA}}
                _NORMAL_STYLE = {"Button": {"background_color": 0xFF444444}}
                for row in range(2):
                    with ui.HStack(height=28, spacing=4):
                        for col in range(3):
                            idx = row * 3 + col
                            b = ui.Button(
                                f"(empty)", height=26,
                                style=_NORMAL_STYLE,
                                clicked_fn=lambda i=idx: self._on_select_backup_btn(i),
                                tooltip="Click to select this backup time",
                            )
                            self._backup_buttons.append(b)

                # Page navigation
                with ui.HStack(height=24, spacing=4):
                    ui.Button(
                        "< Prev", width=60, height=22,
                        clicked_fn=self._on_prev_backup_page,
                        tooltip="Previous 6 backups",
                    )
                    self._page_label = ui.Label(
                        "",
                        alignment=ui.Alignment.CENTER,
                        style={"color": 0xFF999999, "font_size": 11},
                    )
                    ui.Button(
                        "Next >", width=60, height=22,
                        clicked_fn=self._on_next_backup_page,
                        tooltip="Next 6 backups",
                    )

                # Info line
                self._time_info_label = ui.Label(
                    "",
                    style={"color": 0xFF999999, "font_size": 11},
                )

                # Diff preview
                self._diff_label = ui.Label(
                    "",
                    word_wrap=True,
                    style={"color": 0xFFCCCCCC, "font_size": 12},
                )

                ui.Spacer(height=4)

                # Restore + Undo buttons (integrated, single click)
                with ui.HStack(height=30, spacing=8):
                    ui.Button(
                        "Restore to Backup", height=28,
                        clicked_fn=self._on_restore_stage,
                        style={"Button": {"background_color": 0xFF2266AA}},
                        tooltip="Restore Stage to the selected backup time",
                    )
                    self._undo_btn = ui.Button(
                        "Undo", height=28,
                        clicked_fn=self._on_undo,
                        enabled=False,
                        tooltip="Revert to state before last restore",
                    )

                # Progress / result
                self._restore_result_label = ui.Label(
                    "",
                    word_wrap=True,
                    style={"color": 0xFFCCCCCC, "font_size": 11},
                )

    def _on_load_backup_times(self):
        self._set_status("Loading backup times...")
        asyncio.ensure_future(self._async_load_backup_times())

    async def _async_load_backup_times(self):
        try:
            result = await api_get(self._get_api_url(), "api/v1/entities/backup-times")
            self._backup_times_list = result.get("backup_times", [])
            self._backup_sources_list = result.get("backup_sources", [])
            self._selected_backup_idx = 0
            self._backup_page = 0
            if self._backup_times_list:
                self._update_time_display()
                self._set_status(f"[OK] Loaded {len(self._backup_times_list)} backup time(s).")
            else:
                for btn in self._backup_buttons:
                    btn.text = "(empty)"
                    btn.enabled = False
                self._page_label.text = ""
                self._time_info_label.text = ""
                self._diff_label.text = ""
                self._set_status("[INFO] No backup times found.")
        except Exception as e:
            self._set_status(f"[FAIL] Load backup times error: {e}")

    def _on_select_backup_btn(self, btn_idx):
        """Handle click on one of the 6 grid buttons."""
        global_idx = self._backup_page * 6 + btn_idx
        if global_idx >= len(self._backup_times_list):
            return
        self._selected_backup_idx = global_idx
        self._update_time_display()

    def _on_prev_backup_page(self):
        if self._backup_page > 0:
            self._backup_page -= 1
            self._update_time_display()

    def _on_next_backup_page(self):
        max_page = max(0, (len(self._backup_times_list) - 1) // 6)
        if self._backup_page < max_page:
            self._backup_page += 1
            self._update_time_display()

    def _update_time_display(self):
        if not self._backup_times_list:
            return

        total = len(self._backup_times_list)
        max_page = max(0, (total - 1) // 6)
        page_start = self._backup_page * 6

        # Update 6 grid buttons
        for i, btn in enumerate(self._backup_buttons):
            global_idx = page_start + i
            if global_idx < total:
                bt = self._backup_times_list[global_idx]
                # Shorten: show time part only (HH:MM:SS)
                short = bt.split("T")[1][:8] if "T" in bt else bt[:16]
                source = self._backup_sources_list[global_idx] if global_idx < len(self._backup_sources_list) else ""
                src_tag = f" [{source[:3]}]" if source else ""
                btn.text = f"{short}{src_tag}"
                btn.enabled = True
                # Highlight selected
                if global_idx == self._selected_backup_idx:
                    btn.set_style({"Button": {"background_color": 0xFF2266AA}})
                else:
                    btn.set_style({"Button": {"background_color": 0xFF444444}})
            else:
                btn.text = "(empty)"
                btn.enabled = False
                btn.set_style({"Button": {"background_color": 0xFF333333}})

        # Page label
        self._page_label.text = f"Page {self._backup_page + 1}/{max_page + 1} ({total} backups)"

        # Info line for selected
        idx = self._selected_backup_idx
        bt = self._backup_times_list[idx]
        source = self._backup_sources_list[idx] if idx < len(self._backup_sources_list) else ""
        self._time_info_label.text = f"Selected: {bt} | Source: {source}"

        # Load diff preview asynchronously
        asyncio.ensure_future(self._load_diff_preview(bt))

    async def _load_diff_preview(self, backup_time: str):
        """Load diff summary between latest backup and selected backup."""
        try:
            if len(self._backup_times_list) < 2:
                self._diff_label.text = "(only one backup — no diff available)"
                return

            latest = self._backup_times_list[0]
            if backup_time == latest:
                self._diff_label.text = "(this is the latest backup)"
                return

            encoded_a = urllib.parse.quote(backup_time, safe="")
            encoded_b = urllib.parse.quote(latest, safe="")
            result = await api_get(
                self._get_api_url(),
                f"api/v1/entities/diff?time_a={encoded_a}&time_b={encoded_b}",
            )
            added = result.get("added", 0)
            removed = result.get("removed", 0)
            changed = result.get("changed", 0)
            unchanged = result.get("unchanged", 0)
            self._diff_label.text = (
                f"Diff vs latest: Changed={changed}, Added={added}, "
                f"Removed={removed}, Unchanged={unchanged}"
            )
        except Exception as e:
            self._diff_label.text = f"(diff error: {e})"

    # ── Stage Restore Frame ─────────────────────────────────────

    def _on_restore_stage(self):
        if not self._backup_times_list:
            self._set_status("[FAIL] No backup time selected. Load backups first.")
            return

        bt = self._backup_times_list[self._selected_backup_idx]
        self._set_status(f"Restoring Stage to {bt}...")
        self._restore_result_label.text = "Restoring..."

        asyncio.ensure_future(self._async_restore_stage(bt))

    async def _async_restore_stage(self, backup_time: str):
        try:
            # 1. Capture undo snapshot (main thread — Stage API is not thread-safe)
            self._set_status("Capturing undo snapshot...")
            self._undo_snapshot = capture_undo_snapshot()

            # 2. Fetch all data in one API call (executor — network I/O)
            self._set_status("Fetching backup data...")
            encoded = urllib.parse.quote(backup_time, safe="")
            data = await api_get(
                self._get_api_url(),
                f"api/v1/entities/restore-all?backup_time={encoded}",
            )

            entities = data.get("entities", [])
            prim_snapshots = data.get("prim_snapshots", [])

            if not entities:
                self._set_status("[INFO] No entities found at this backup time.")
                self._restore_result_label.text = "No data to restore."
                return

            # 3. Apply complete restore (main thread — Stage API is not thread-safe)
            self._restore_result_label.text = f"Restoring {len(entities)} entities, {len(prim_snapshots)} prim snapshots..."
            self._set_status(f"Applying {len(entities)} entities...")

            result = restore_stage(
                entities=entities,
                prim_snapshots=prim_snapshots,
                progress_callback=None,
            )
            entities_restored, props_applied, props_failed, prims_deleted, warnings = result

            # 4. Enable undo button
            self._undo_btn.enabled = True

            # 5. Show result
            summary = (
                f"Restored {entities_restored} entities\n"
                f"Properties applied: {props_applied}\n"
                f"Properties failed: {props_failed}\n"
                f"Prims deleted: {prims_deleted}"
            )
            if warnings:
                summary += f"\nWarnings ({len(warnings)}):\n"
                for w in warnings[:10]:
                    summary += f"  - {w}\n"
                if len(warnings) > 10:
                    summary += f"  ... and {len(warnings) - 10} more"

            self._restore_result_label.text = summary
            self._set_status(f"[OK] Stage restored to {backup_time}")

        except Exception as e:
            self._set_status(f"[FAIL] Restore error: {e}")
            self._restore_result_label.text = f"Error: {e}"

    def _on_undo(self):
        if not self._undo_snapshot:
            self._set_status("[INFO] No undo snapshot available.")
            return

        self._set_status("Applying undo snapshot...")
        try:
            applied, failed, warnings = apply_undo_snapshot(self._undo_snapshot)
            self._undo_snapshot = None
            self._undo_btn.enabled = False
            self._restore_result_label.text = (
                f"Undo complete: {applied} properties restored, {failed} failed"
            )
            if warnings:
                self._restore_result_label.text += f"\nWarnings: {len(warnings)}"
            self._set_status("[OK] Undo applied.")
        except Exception as e:
            self._set_status(f"[FAIL] Undo error: {e}")


    # ── M&S Simulation Frame ──────────────────────────────────

    # ── Simulation Capture & Replay Frame ────────────────────────

    def _create_capture_frame(self):
        frame = CollapsableFrame("Simulation Capture & Replay", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Capture simulation property changes in real-time.\n"
                    "Enable Auto Capture, then press Play to start.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                # Auto Capture Toggle
                with ui.HStack(height=28, spacing=8):
                    ui.Label("Auto Capture:", width=90)
                    self._auto_capture_cb = ui.CheckBox(width=20)
                    self._auto_capture_cb.model.set_value(False)
                    self._auto_capture_cb.model.add_value_changed_fn(
                        self._on_auto_capture_toggled,
                    )
                    self._auto_capture_status = ui.Label(
                        "OFF", style={"color": 0xFFFF6666},
                    )

                ui.Spacer(height=4)

                # Capture Scope
                ui.Label("Capture Scope:", style={"color": 0xFF999999, "font_size": 11})
                self._scope_collection = ui.RadioCollection()
                with ui.HStack(height=24, spacing=8):
                    ui.RadioButton(
                        text="Auto Dynamic",
                        radio_collection=self._scope_collection, width=110,
                    )
                    ui.RadioButton(
                        text="Scoped",
                        radio_collection=self._scope_collection, width=70,
                    )
                    ui.RadioButton(
                        text="Full Stage",
                        radio_collection=self._scope_collection, width=80,
                    )
                self._scope_path_field = StringField(
                    "Scope Path",
                    default_value="/World",
                    tooltip="Root path for Scoped capture mode",
                    read_only=False,
                )
                self.wrapped_ui_elements.append(self._scope_path_field)

                # Tracked Prims count
                self._tracked_prims_label = ui.Label(
                    "Tracked Prims: 0",
                    style={"color": 0xFF99CCFF, "font_size": 11},
                )

                ui.Spacer(height=6)

                # Live Capture Status
                self._capture_status_label = ui.Label(
                    "Status: Idle",
                    style={"color": 0xFFCCCCCC, "font_size": 12},
                )
                self._capture_count_label = ui.Label(
                    "Captured deltas: 0",
                    style={"color": 0xFF99CCFF, "font_size": 13},
                )
                self._session_id_label = ui.Label(
                    "Session: --",
                    style={"color": 0xFF999999, "font_size": 11},
                )

                ui.Spacer(height=4)

                # Manual controls
                with ui.HStack(height=28, spacing=8):
                    ui.Button(
                        "Flush Now", height=26,
                        clicked_fn=self._on_capture_flush,
                        style={"Button": {"background_color": 0xFF225588}},
                        tooltip="Manually flush capture buffer to Lakehouse",
                    )
                    ui.Button(
                        "Clear Buffer", height=26,
                        clicked_fn=self._on_clear_capture_buffer,
                        tooltip="Clear all captured deltas from memory",
                    )

                self._capture_flush_status = ui.Label(
                    "Last flush: --",
                    style={"color": 0xFF99CCFF, "font_size": 11},
                )

                ui.Spacer(height=6)

                # Replay Mode indicator
                self._replay_mode_label = ui.Label(
                    "",
                    style={"color": 0xFFFFAA00, "font_size": 12},
                )

                # Session History (collapsed)
                with CollapsableFrame("Session History", collapsed=True):
                    with ui.VStack(style=get_style(), spacing=5, height=0):
                        ui.Button(
                            "Load Sessions", height=26,
                            clicked_fn=self._on_load_sessions,
                            tooltip="Fetch past simulation sessions from API",
                        )
                        self._session_list_label = ui.Label(
                            "No sessions loaded.",
                            word_wrap=True,
                            style={"color": 0xFFCCCCCC, "font_size": 11},
                        )

                        ui.Spacer(height=4)

                        # Session selection buttons (populated dynamically)
                        self._session_buttons_container = ui.VStack(
                            spacing=2, height=0,
                        )

                        ui.Spacer(height=4)

                        # Bake / Remove Replay controls
                        with ui.HStack(height=28, spacing=8):
                            ui.Button(
                                "Bake to Timeline", height=26,
                                clicked_fn=self._on_bake_timeline,
                                style={"Button": {"background_color": 0xFF226644}},
                                tooltip="Bake selected session deltas as USD TimeSamples",
                            )
                            ui.Button(
                                "Reset Replay", height=26,
                                clicked_fn=self._on_remove_replay,
                                style={"Button": {"background_color": 0xFF664422}},
                                tooltip="Remove replay sublayer, restore original timeline range, stop playback",
                            )
                            ui.Button(
                                "Cancel Bake", height=26,
                                clicked_fn=self._on_cancel_bake,
                                tooltip="Cancel in-progress baking",
                            )

                        self._bake_progress_label = ui.Label(
                            "",
                            style={"color": 0xFF99CCFF, "font_size": 11},
                        )

    # ── Capture & Replay Callbacks ─────────────────────────────

    def _on_auto_capture_toggled(self, model):
        self._auto_capture_enabled = model.get_value_as_bool()
        if self._auto_capture_enabled:
            self._auto_capture_status.text = "ON"
            self._auto_capture_status.set_style({"color": 0xFF66FF66})
        else:
            self._auto_capture_status.text = "OFF"
            self._auto_capture_status.set_style({"color": 0xFFFF6666})

    def _get_capture_scope(self) -> CaptureScope:
        idx = self._scope_collection.model.get_value_as_int()
        return [CaptureScope.AUTO_DYNAMIC, CaptureScope.SCOPED, CaptureScope.FULL_STAGE][idx]

    def _on_play_started(self):
        """Timeline PLAY — Auto Capture 활성 시 세션 시작."""
        if not self._auto_capture_enabled:
            return
        # Replay 모드 활성 시 캡처 방지 (리플레이 데이터 재캡처 무한 루프 방지)
        if self._timeline_baker.is_replay_active:
            return
        scope = self._get_capture_scope()
        api_url = self._get_api_url()
        stage = omni.usd.get_context().get_stage()
        scene_path = stage.GetRootLayer().identifier if stage else "unknown"
        try:
            msg = self._coordinator.start_session(scene_path, scope, api_url)
            self._capture_status_label.text = "Status: Capturing..."
            self._capture_status_label.set_style({"color": 0xFF66FF66})
            sid = self._coordinator.simulation_id or "--"
            self._session_id_label.text = f"Session: {sid[:8]}..."
            # Update tracked prims count
            try:
                count = len(self._coordinator.entity_registry.get_tracked_prims())
                self._tracked_prims_label.text = f"Tracked Prims: {count}"
            except Exception:
                pass
            self._set_status(f"[OK] {msg}")
        except Exception as e:
            self._set_status(f"[FAIL] Capture start error: {e}")

    def _on_play_stopped(self):
        """Timeline STOP — 활성 세션이면 종료."""
        if not self._coordinator.is_active:
            return
        try:
            msg = self._coordinator.stop_session()
            total = self._coordinator.session_stats.get("total_deltas", 0)
            self._capture_status_label.text = "Status: Idle"
            self._capture_status_label.set_style({"color": 0xFFCCCCCC})
            self._capture_count_label.text = f"Captured deltas: {total}"
            self._session_id_label.text = "Session: --"
            self._set_status(f"[OK] {msg}")
        except Exception as e:
            self._set_status(f"[FAIL] Capture stop error: {e}")

    def _on_capture_flush(self):
        if not self._coordinator.is_active:
            self._set_status("[INFO] No active capture session")
            return
        api_url = self._get_api_url()
        asyncio.ensure_future(self._async_capture_flush(api_url))

    async def _async_capture_flush(self, api_url):
        try:
            count, had_error, msg = await self._coordinator.flush_buffer(api_url)
            if had_error:
                self._capture_flush_status.text = f"Flush error: {msg}"
            else:
                self._capture_flush_status.text = f"Flushed {count} deltas"
                self._capture_count_label.text = (
                    f"Captured deltas: {self._coordinator.buffer_count}"
                )
        except Exception as e:
            self._capture_flush_status.text = f"Flush error: {e}"

    def _on_clear_capture_buffer(self):
        with self._coordinator._buffer_lock:
            self._coordinator._buffer.clear()
        self._capture_count_label.text = "Captured deltas: 0"
        self._set_status("[OK] Capture buffer cleared")

    def _on_load_sessions(self):
        asyncio.ensure_future(self._async_load_sessions())

    async def _async_load_sessions(self):
        try:
            api_url = self._get_api_url()
            result = await api_get(api_url, "api/v1/simulation/sessions")
            sessions = result if isinstance(result, list) else result.get("sessions", [])
            if not sessions:
                self._session_list_label.text = "No sessions found."
                self._sessions_cache = []
                return
            self._sessions_cache = sessions[:20]
            # Validate stale selection — clear if session no longer in list
            if self._selected_session_id:
                cached_ids = {s.get("simulation_id") for s in self._sessions_cache}
                if self._selected_session_id not in cached_ids:
                    self._selected_session_id = None
            self._render_session_list_and_buttons()
        except Exception as e:
            self._session_list_label.text = f"Error: {e}"

    def _on_select_session(self, idx):
        if idx < len(self._sessions_cache):
            sess = self._sessions_cache[idx]
            self._selected_session_id = sess.get("simulation_id")
            self._set_status(f"[OK] Selected session: {self._selected_session_id[:8]}...")
            # Defer re-render to next frame — Container.clear() forbidden during draw callback
            # Coalesce rapid clicks: skip if rerender already pending
            if getattr(self, "_rerender_pending", False):
                return
            self._rerender_pending = True
            async def _deferred_rerender():
                import omni.kit.app
                await omni.kit.app.get_app().next_update_async()
                self._rerender_pending = False
                self._render_session_list_and_buttons()
            asyncio.ensure_future(_deferred_rerender())

    def _render_session_list_and_buttons(self):
        """Re-render session list text + Nx2 button grid from cache."""
        lines = []
        for i, sess in enumerate(self._sessions_cache):
            sid = sess.get("simulation_id", "?")[:8]
            status = sess.get("status", "?")
            info = _format_session_info(sess)
            marker = " <<" if sess.get("simulation_id") == self._selected_session_id else ""
            lines.append(f"[{i}] {sid}... | {status} | {info}{marker}")
        self._session_list_label.text = "\n".join(lines)
        # Nx2 button grid
        _COLS = 2
        visible = self._sessions_cache[:10]
        self._session_buttons_container.clear()
        with self._session_buttons_container:
            for row_start in range(0, len(visible), _COLS):
                with ui.HStack(height=26, spacing=4):
                    for col in range(_COLS):
                        idx = row_start + col
                        if idx < len(visible):
                            sess = visible[idx]
                            short = sess.get("simulation_id", "?")[:8]
                            status = sess.get("status", "?")
                            info = _format_session_info(sess)
                            is_sel = sess.get("simulation_id") == self._selected_session_id
                            bg = 0xFF2266AA if is_sel else 0xFF444444
                            ui.Button(
                                f"{short}.. {info}",
                                height=24,
                                clicked_fn=lambda i=idx: self._on_select_session(i),
                                style={"Button": {"background_color": bg}},
                                tooltip=f"{sess.get('simulation_id','?')} ({status})",
                            )
                        else:
                            ui.Spacer()

    def _on_bake_timeline(self):
        if not self._selected_session_id:
            self._set_status("[INFO] Select a session first")
            return
        if self._timeline_baker.is_baking:
            self._set_status("[INFO] Baking already in progress")
            return
        api_url = self._get_api_url()
        asyncio.ensure_future(
            self._async_bake_timeline(self._selected_session_id, api_url),
        )

    async def _async_bake_timeline(self, simulation_id, api_url):
        def on_progress(current, total):
            self._bake_progress_label.text = f"Baking: {current}/{total} deltas..."

        try:
            self._bake_progress_label.text = "Baking: fetching deltas..."
            self._set_status(f"[INFO] Baking session {simulation_id[:8]}...")
            result = await self._timeline_baker.bake_session(
                simulation_id=simulation_id,
                api_url=api_url,
                on_progress=on_progress,
            )
            if result is None:
                self._bake_progress_label.text = "Bake cancelled."
                self._set_status("[INFO] Bake cancelled")
            else:
                frames = self._timeline_baker.baked_frame_count
                self._bake_progress_label.text = f"Bake complete! {frames} frames"
                self._replay_mode_label.text = (
                    "REPLAY MODE ACTIVE (physics-free)"
                )
                self._set_status(
                    f"[OK] Timeline baked — {frames} frames, replaying without physics"
                )
                # Physics-free replay: 물리 시뮬레이션 비활성화 후 재생
                # TimeSamples sublayer가 애니메이션을 구동하므로 physics 불필요
                try:
                    import omni.physx
                    physx = omni.physx.get_physx_interface()
                    physx.force_load_physics_from_usd()
                except Exception:
                    pass
                # 자동 재생 시작 (physics 없이 timeline만 재생)
                try:
                    timeline = omni.timeline.get_timeline_interface()
                    timeline.set_current_time(0.0)
                    timeline.play()
                except Exception:
                    pass
        except Exception as e:
            self._bake_progress_label.text = f"Bake error: {e}"
            self._set_status(f"[FAIL] Bake error: {e}")

    def _on_remove_replay(self):
        try:
            self._timeline_baker.restore_timeline()
            self._replay_mode_label.text = ""
            self._bake_progress_label.text = ""
            self._set_status("[OK] Replay removed — timeline range restored to original")
        except Exception as e:
            self._set_status(f"[FAIL] Remove replay error: {e}")

    def _on_cancel_bake(self):
        if self._timeline_baker.is_baking:
            self._timeline_baker.cancel_bake()
            self._set_status("[INFO] Cancelling bake...")
        else:
            self._set_status("[INFO] No bake in progress")

    # ── Nucleus Reopen Frame ────────────────────────────────────

    def _create_nucleus_frame(self):
        frame = CollapsableFrame("Nucleus", collapsed=True)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Current Stage file info and Nucleus reopen.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                # File info display
                self._nucleus_file_label = ui.Label(
                    "(no stage open)",
                    word_wrap=True,
                    style={"color": 0xFFCCCCCC, "font_size": 12},
                )

                with ui.HStack(height=28, spacing=8):
                    ui.Button(
                        "Show File Info", height=26,
                        clicked_fn=self._on_show_nucleus_info,
                        tooltip="Display current Stage file path and layer info",
                    )
                    ui.Button(
                        "Reopen from Nucleus", height=26,
                        clicked_fn=self._on_nucleus_reopen,
                        style={"Button": {"background_color": 0xFF664422}},
                        tooltip="Reopen current .usd file from Nucleus server (discards unsaved changes)",
                    )

    def _on_show_nucleus_info(self):
        try:
            ctx = omni.usd.get_context()
            stage = ctx.get_stage()
            if not stage:
                self._nucleus_file_label.text = "(no active Stage)"
                return

            root_layer = stage.GetRootLayer()
            file_path = root_layer.identifier or "(unsaved)"

            # Collect sublayer info
            sublayers = list(root_layer.subLayerPaths)
            sub_count = len(sublayers)

            # Count root-level prims under /World
            world_spec = root_layer.GetPrimAtPath("/World")
            world_children = len(list(world_spec.nameChildren)) if world_spec else 0

            info = (
                f"File: {file_path}\n"
                f"Sublayers: {sub_count}\n"
                f"/World children (root layer): {world_children}"
            )
            if sublayers:
                info += "\nSublayer paths:"
                for sl in sublayers[:5]:
                    info += f"\n  - {sl}"
                if sub_count > 5:
                    info += f"\n  ... and {sub_count - 5} more"

            self._nucleus_file_label.text = info
            self._set_status("[OK] File info loaded.")
        except Exception as e:
            self._nucleus_file_label.text = f"Error: {e}"

    def _on_nucleus_reopen(self):
        try:
            ctx = omni.usd.get_context()
            stage = ctx.get_stage()
            if not stage:
                self._set_status("[FAIL] No active Stage.")
                return

            root_layer = stage.GetRootLayer()
            file_path = root_layer.identifier
            if not file_path:
                self._set_status("[FAIL] Cannot determine current file path.")
                return

            self._set_status(f"Reopening: {file_path}")
            ctx.open_stage(file_path)
            self._set_status(f"[OK] Reopened: {file_path}")
        except Exception as e:
            self._set_status(f"[FAIL] Reopen error: {e}")

    # ── Status Frame ────────────────────────────────────────────

    def _create_status_frame(self):
        frame = CollapsableFrame("Status Log", collapsed=True)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                self._status_block = TextBlock(
                    "Status",
                    num_lines=5,
                    tooltip="Operation log",
                    include_copy_button=True,
                )
                self.wrapped_ui_elements.append(self._status_block)

    def _set_status(self, msg: str):
        try:
            if self._status_block:
                self._status_block.set_text(msg)
        except Exception as e:
            print(f"[KKR.TimeTravel] Status update error: {e}")
