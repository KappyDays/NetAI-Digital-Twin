"""Time Travel Extension — UI Builder.

Provides:
- API Settings: URL config + health check
- Backup Timeline: Browse backup timestamps with diff preview
- Stage Restore: 3-mode restore (changes only / full entity / full all) + Undo
- Entity Restore: Single entity restore
- Nucleus Reopen: Reopen current .usd from Nucleus
"""

import asyncio
import json
import os
import urllib.error
import urllib.parse

import omni.ui as ui
import omni.usd
from isaacsim.gui.components.element_wrappers import (
    Button,
    CollapsableFrame,
    StringField,
    TextBlock,
)
from isaacsim.gui.components.ui_utils import get_style

from .api_client import api_get_sync, api_get
from .restore_engine import (
    MODE_CHANGES_ONLY,
    MODE_FULL_ENTITY,
    MODE_FULL_ALL,
    capture_undo_snapshot,
    apply_undo_snapshot,
    restore_stage,
    restore_single_entity,
)

DEFAULT_API_BASE_URL = os.getenv("LAKEHOUSE_API_URL", "http://localhost:8100")


class UIBuilder:
    def __init__(self):
        self.frames = []
        self.wrapped_ui_elements = []
        # State
        self._backup_times_list = []
        self._backup_sources_list = []
        self._selected_backup_idx = 0
        self._entities_list = []
        self._selected_entity_idx = 0
        self._restore_mode = MODE_CHANGES_ONLY
        self._undo_snapshot = None
        self._status_block = None
        self._diff_label = None

    # =========================================================================
    #  Callbacks wired by extension.py
    # =========================================================================

    def on_menu_callback(self):
        pass

    def on_timeline_event(self, event):
        pass

    def on_stage_event(self, event):
        pass

    def cleanup(self):
        self.wrapped_ui_elements = []

    # =========================================================================
    #  Build UI
    # =========================================================================

    def build_ui(self):
        self._create_status_frame()
        self._create_api_settings_frame()
        self._create_timeline_frame()
        self._create_stage_restore_frame()
        self._create_entity_restore_frame()
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
        print("[KKR.TimeTravel] _on_health_check called")
        try:
            url = self._get_api_url()
            print(f"[KKR.TimeTravel] API URL: {url}")
            result = api_get_sync(url, "api/v1/health")
            print(f"[KKR.TimeTravel] Result: {result}")
            self._set_status(f"[OK] API connected: {result.get('status', 'unknown')}")
        except Exception as e:
            print(f"[KKR.TimeTravel] Error: {e}")
            self._set_status(f"[FAIL] Cannot connect to API: {e}")

    # ── Backup Timeline Frame ───────────────────────────────────

    def _create_timeline_frame(self):
        frame = CollapsableFrame("Backup Timeline", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Select a backup timestamp to restore from.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                # Navigation: << [timestamp] >>
                ui.Label("Backup Time", style={"color": 0xFF999999, "font_size": 11})
                with ui.HStack(height=26, spacing=4):
                    ui.Button(
                        "<<", width=40, height=24,
                        clicked_fn=self._on_prev_backup_time,
                        tooltip="Older backup",
                    )
                    self._time_label = ui.Label(
                        "(not loaded)",
                        alignment=ui.Alignment.CENTER,
                        style={"color": 0xFFEEEEEE, "font_size": 13},
                    )
                    ui.Button(
                        ">>", width=40, height=24,
                        clicked_fn=self._on_next_backup_time,
                        tooltip="Newer backup",
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

                # Load button
                btn = Button(
                    "Load Backups",
                    "LOAD BACKUP TIMES",
                    tooltip="Fetch available backup timestamps from API",
                    on_click_fn=self._on_load_backup_times,
                )
                self.wrapped_ui_elements.append(btn)

    def _on_load_backup_times(self):
        try:
            result = api_get_sync(self._get_api_url(), "api/v1/entities/backup-times")
            self._backup_times_list = result.get("backup_times", [])
            self._backup_sources_list = result.get("backup_sources", [])
            self._selected_backup_idx = 0
            if self._backup_times_list:
                self._update_time_display()
                self._set_status(f"[OK] Loaded {len(self._backup_times_list)} backup time(s).")
            else:
                self._time_label.text = "(no backups found)"
                self._time_info_label.text = ""
                self._diff_label.text = ""
                self._set_status("[INFO] No backup times found.")
        except Exception as e:
            self._set_status(f"[FAIL] Load backup times error: {e}")

    def _on_prev_backup_time(self):
        if self._backup_times_list and self._selected_backup_idx < len(self._backup_times_list) - 1:
            self._selected_backup_idx += 1
            self._update_time_display()

    def _on_next_backup_time(self):
        if self._backup_times_list and self._selected_backup_idx > 0:
            self._selected_backup_idx -= 1
            self._update_time_display()

    def _update_time_display(self):
        if not self._backup_times_list:
            return
        idx = self._selected_backup_idx
        bt = self._backup_times_list[idx]
        self._time_label.text = bt
        source = self._backup_sources_list[idx] if idx < len(self._backup_sources_list) else ""
        self._time_info_label.text = f"[{idx + 1}/{len(self._backup_times_list)}] Source: {source}"

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

    def _create_stage_restore_frame(self):
        frame = CollapsableFrame("Stage Restore", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Restore entire Stage to the selected backup time.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                # Restore mode radio buttons
                ui.Label("Restore Mode", style={"color": 0xFF999999, "font_size": 11})
                self._mode_collection = ui.RadioCollection()
                with ui.VStack(spacing=2):
                    with ui.HStack(height=20):
                        ui.RadioButton(
                            radio_collection=self._mode_collection,
                            width=20, height=20,
                        )
                        ui.Label("Changes Only (safe)", style={"font_size": 12})
                    with ui.HStack(height=20):
                        ui.RadioButton(
                            radio_collection=self._mode_collection,
                            width=20, height=20,
                        )
                        ui.Label("Full Restore — Entity (protect Looks/Camera)", style={"font_size": 12})
                    with ui.HStack(height=20):
                        ui.RadioButton(
                            radio_collection=self._mode_collection,
                            width=20, height=20,
                        )
                        ui.Label("Full Restore — All (deletes non-backup Prims)", style={"font_size": 12, "color": 0xFF5555FF})
                self._mode_collection.model.set_value(0)  # Default: changes only

                ui.Spacer(height=4)

                # Buttons
                with ui.HStack(height=30, spacing=8):
                    ui.Button(
                        "Restore Stage", height=28,
                        clicked_fn=self._on_restore_stage,
                        style={"Button": {"background_color": 0xFF2266AA}},
                        tooltip="Apply backup overrides to current Stage",
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

    def _get_restore_mode(self) -> str:
        idx = self._mode_collection.model.get_value_as_int()
        self._full_all_confirmed = False  # Reset on mode change
        return [MODE_CHANGES_ONLY, MODE_FULL_ENTITY, MODE_FULL_ALL][idx]

    def _on_restore_stage(self):
        if not self._backup_times_list:
            self._set_status("[FAIL] No backup time selected. Load backups first.")
            return

        mode = self._get_restore_mode()

        # Confirm for full_all mode
        if mode == MODE_FULL_ALL:
            if not getattr(self, "_full_all_confirmed", False):
                self._set_status(
                    "[WARNING] Full Restore (All) will delete ALL non-backup Prims "
                    "including Looks, Camera_presets. Click 'Restore Stage' again to confirm."
                )
                self._restore_result_label.text = (
                    "*** CONFIRM: Full Restore (All) mode selected ***\n"
                    "This will delete Looks, Camera_presets, and all non-backup Prims.\n"
                    "Click 'Restore Stage' again to proceed, or change mode to cancel."
                )
                self._full_all_confirmed = True
                return
            self._full_all_confirmed = False

        bt = self._backup_times_list[self._selected_backup_idx]
        self._set_status(f"Restoring Stage to {bt}...")
        self._restore_result_label.text = "Restoring..."

        asyncio.ensure_future(self._async_restore_stage(bt, mode))

    async def _async_restore_stage(self, backup_time: str, mode: str):
        try:
            # 1. Capture undo snapshot before restore
            self._set_status("Capturing undo snapshot...")
            loop = asyncio.get_running_loop()
            self._undo_snapshot = await loop.run_in_executor(None, capture_undo_snapshot)

            # 2. Fetch all data in one API call
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

            # 3. Apply restore
            self._restore_result_label.text = f"Restoring {len(entities)} entities, {len(prim_snapshots)} prim snapshots..."
            self._set_status(f"Applying {len(entities)} entities...")

            def do_restore():
                return restore_stage(
                    entities=entities,
                    prim_snapshots=prim_snapshots,
                    mode=mode,
                    progress_callback=None,
                )

            result = await loop.run_in_executor(None, do_restore)
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

    # ── Entity Restore Frame ────────────────────────────────────

    def _create_entity_restore_frame(self):
        frame = CollapsableFrame("Entity Restore", collapsed=True)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Restore a single entity from the selected backup time.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                # Entity navigation
                ui.Label("Entity", style={"color": 0xFF999999, "font_size": 11})
                with ui.HStack(height=26, spacing=4):
                    ui.Button(
                        "<<", width=40, height=24,
                        clicked_fn=self._on_prev_entity,
                    )
                    self._entity_label = ui.Label(
                        "(not loaded)",
                        alignment=ui.Alignment.CENTER,
                        style={"color": 0xFFEEEEEE, "font_size": 13},
                    )
                    ui.Button(
                        ">>", width=40, height=24,
                        clicked_fn=self._on_next_entity,
                    )

                with ui.HStack(height=28, spacing=8):
                    btn = Button(
                        "Load Entities",
                        "LOAD ENTITIES",
                        tooltip="Load entity list for selected backup time",
                        on_click_fn=self._on_load_entities,
                    )
                    self.wrapped_ui_elements.append(btn)

                ui.Button(
                    "Restore Entity", height=28,
                    clicked_fn=self._on_restore_entity,
                    style={"Button": {"background_color": 0xFF226644}},
                    tooltip="Restore selected entity overrides to Stage",
                )

                self._entity_result_label = ui.Label(
                    "",
                    word_wrap=True,
                    style={"color": 0xFFCCCCCC, "font_size": 11},
                )

    def _on_load_entities(self):
        if not self._backup_times_list:
            self._set_status("[FAIL] No backup time selected. Load backups first.")
            return

        bt = self._backup_times_list[self._selected_backup_idx]
        try:
            encoded = urllib.parse.quote(bt, safe="")
            result = api_get_sync(self._get_api_url(), f"api/v1/entities/list?backup_time={encoded}")
            self._entities_list = result.get("entities", [])
            self._selected_entity_idx = 0
            if self._entities_list:
                self._update_entity_display()
                self._set_status(f"[OK] Loaded {len(self._entities_list)} entities.")
            else:
                self._entity_label.text = "(no entities)"
                self._set_status("[INFO] No entities at this backup time.")
        except Exception as e:
            self._set_status(f"[FAIL] Load entities error: {e}")

    def _on_prev_entity(self):
        if self._entities_list and self._selected_entity_idx > 0:
            self._selected_entity_idx -= 1
            self._update_entity_display()

    def _on_next_entity(self):
        if self._entities_list and self._selected_entity_idx < len(self._entities_list) - 1:
            self._selected_entity_idx += 1
            self._update_entity_display()

    def _update_entity_display(self):
        if not self._entities_list:
            return
        idx = self._selected_entity_idx
        entity = self._entities_list[idx]
        ep = entity.get("entity_path", "unknown") if isinstance(entity, dict) else str(entity)
        self._entity_label.text = ep

    def _on_restore_entity(self):
        if not self._entities_list or not self._backup_times_list:
            self._set_status("[FAIL] No entity selected.")
            return

        bt = self._backup_times_list[self._selected_backup_idx]
        entity = self._entities_list[self._selected_entity_idx]
        ep = entity.get("entity_path", "") if isinstance(entity, dict) else str(entity)

        if not ep:
            self._set_status("[FAIL] Invalid entity path.")
            return

        asyncio.ensure_future(self._async_restore_entity(bt, ep))

    async def _async_restore_entity(self, backup_time: str, entity_path: str):
        try:
            # Capture undo snapshot before restore
            import asyncio as _asyncio
            loop = _asyncio.get_running_loop()
            self._undo_snapshot = await loop.run_in_executor(None, capture_undo_snapshot)

            encoded_ep = urllib.parse.quote(entity_path.lstrip("/"), safe="")
            encoded_bt = urllib.parse.quote(backup_time, safe="")
            data = await api_get(
                self._get_api_url(),
                f"api/v1/entities/{encoded_ep}/restore?backup_time={encoded_bt}",
            )

            prim_snapshots = data.get("prim_snapshots", [])
            if not prim_snapshots:
                self._entity_result_label.text = "No prim snapshots to restore."
                return

            loop = asyncio.get_running_loop()

            def do_restore():
                return restore_single_entity(entity_path, prim_snapshots)

            applied, failed, warnings = await loop.run_in_executor(None, do_restore)

            self._undo_btn.enabled = True
            self._entity_result_label.text = (
                f"Entity restored: {applied} properties applied, {failed} failed"
            )
            if warnings:
                self._entity_result_label.text += f"\nWarnings: {len(warnings)}"
            self._set_status(f"[OK] Entity {entity_path} restored.")

        except Exception as e:
            self._set_status(f"[FAIL] Entity restore error: {e}")
            self._entity_result_label.text = f"Error: {e}"

    # ── Nucleus Reopen Frame ────────────────────────────────────

    def _create_nucleus_frame(self):
        frame = CollapsableFrame("Nucleus", collapsed=True)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Reopen the current USD file from Nucleus (discards unsaved changes).",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )
                ui.Button(
                    "Reopen from Nucleus", height=28,
                    clicked_fn=self._on_nucleus_reopen,
                    style={"Button": {"background_color": 0xFF664422}},
                    tooltip="Reopen current .usd file from Nucleus server",
                )

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
