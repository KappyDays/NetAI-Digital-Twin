"""Capture Coordinator — M&S 캡처 세션 라이프사이클 관리.

4-Pipeline 캡처 아키텍처의 중심 오케스트레이터:
  - 세션 시작/종료 (API 등록/종료 포함)
  - sequence_id 단조증가 카운터 관리 (thread-safe)
  - sim_step 추적 (PhysicsSampler 콜백에서 갱신)
  - delta 버퍼 수집 (PhysicsSampler + UsdChangeWatcher → add_delta)
  - threshold 기반 auto-flush + 수동 flush_buffer

Pipeline:
  PhysicsSampler   → add_delta(capture_source="physics")
  UsdChangeWatcher → add_delta(capture_source="usd_notice")
"""

import asyncio
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import omni.usd

from .api_client import api_post_json
from .entity_registry import EntityRegistry
from .physics_sampler import PhysicsSampler
from .property_authority_map import PropertyAuthorityMap
from .usd_change_watcher import UsdChangeWatcher

# Entity ID — nucleus_pipeline/usd_parser.py 와 동일 네임스페이스
_ENTITY_NAMESPACE = uuid.NAMESPACE_URL

# Auto-flush 기본값
_DEFAULT_FLUSH_THRESHOLD = 500
_DEFAULT_MIN_FLUSH_INTERVAL = 2.0  # seconds


class CaptureScope(Enum):
    """캡처 범위 선택."""
    AUTO_DYNAMIC = "auto_dynamic"   # PhysicsRigidBodyAPI prim 자동 감지
    SCOPED = "scoped"               # 사용자 지정 경로만
    FULL_STAGE = "full_stage"       # /World 전체


class CaptureCoordinator:
    """M&S 캡처 세션 오케스트레이터.

    Usage:
        coordinator = CaptureCoordinator()
        coordinator.start_session("/World/Scene", CaptureScope.AUTO_DYNAMIC, "http://localhost:8100")
        # ... 시뮬레이션 진행 ...
        await coordinator.flush_buffer("http://localhost:8100")
        coordinator.stop_session()
    """

    def __init__(self):
        # Sub-components
        self._authority_map = PropertyAuthorityMap()
        self._physics_sampler = PhysicsSampler(self)
        self._usd_watcher = UsdChangeWatcher(self)
        self._entity_registry = EntityRegistry()

        # Session state
        self._session_id: Optional[str] = None
        self._simulation_id: Optional[str] = None
        self._is_active: bool = False
        self._api_url: Optional[str] = None
        self._scene_path: Optional[str] = None
        self._scope: CaptureScope = CaptureScope.AUTO_DYNAMIC
        self._session_start_time: float = 0.0

        # sequence_id — thread-safe 단조증가 카운터
        self._sequence_lock = threading.Lock()
        self._sequence_counter: int = 0

        # sim_step — PhysicsSampler._on_physics_step에서 갱신
        self._current_sim_step: int = 0

        # Delta 버퍼
        self._buffer: list[dict] = []
        self._buffer_lock = threading.Lock()

        # Auto-flush 설정
        self._auto_flush_threshold: int = _DEFAULT_FLUSH_THRESHOLD
        self._min_flush_interval: float = _DEFAULT_MIN_FLUSH_INTERVAL
        self._last_flush_time: float = 0.0
        self._flush_in_flight: bool = False  # flush 중복 방지

        # 통계
        self._stats = {
            "total_deltas": 0,
            "total_flushes": 0,
            "physics_deltas": 0,
            "usd_notice_deltas": 0,
            "flush_errors": 0,
        }

    # -- Component 접근 -------------------------------------------------------

    @property
    def authority_map(self) -> PropertyAuthorityMap:
        return self._authority_map

    @property
    def physics_sampler(self) -> PhysicsSampler:
        return self._physics_sampler

    @property
    def usd_watcher(self) -> UsdChangeWatcher:
        return self._usd_watcher

    @property
    def entity_registry(self) -> EntityRegistry:
        return self._entity_registry

    # -- Properties ----------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def buffer_count(self) -> int:
        return len(self._buffer)

    @property
    def simulation_id(self) -> Optional[str]:
        return self._simulation_id

    @property
    def session_stats(self) -> dict:
        return dict(self._stats)

    @property
    def current_sim_step(self) -> int:
        return self._current_sim_step

    def update_sim_step(self, step: int):
        """PhysicsSampler에서 스텝 번호 갱신 시 호출."""
        self._current_sim_step = step

    # -- Session Lifecycle ---------------------------------------------------

    def start_session(
        self,
        scene_path: str,
        capture_scope: CaptureScope,
        api_url: str,
        decimation: int = 6,
    ) -> str:
        """캡처 세션 시작.

        1. 세션 ID / simulation_id 생성
        2. API에 세션 등록 (POST /api/v1/simulation/sessions)
        3. PhysicsSampler + UsdChangeWatcher 시작

        Args:
            scene_path: USD 씬 경로 (예: /World/Scene)
            capture_scope: 캡처 범위 enum
            api_url: Lakehouse API base URL
            decimation: 물리 스텝 decimation (N 스텝당 1회)

        Returns:
            상태 메시지
        """
        if self._is_active:
            return "세션이 이미 활성 상태입니다"

        self._scene_path = scene_path
        self._scope = capture_scope
        self._api_url = api_url
        self._session_id = str(uuid.uuid4())
        self._simulation_id = str(uuid.uuid4())
        self._session_start_time = time.time()
        self._sequence_counter = 0
        self._current_sim_step = 0
        self._last_flush_time = 0.0
        self._flush_in_flight = False
        self._authority_map.clear()
        self._stats = {
            "total_deltas": 0,
            "total_flushes": 0,
            "physics_deltas": 0,
            "usd_notice_deltas": 0,
            "flush_errors": 0,
        }

        with self._buffer_lock:
            self._buffer.clear()

        # EntityRegistry 초기화 후 Stage 스캔
        self._entity_registry.clear()
        if capture_scope in (CaptureScope.AUTO_DYNAMIC, CaptureScope.FULL_STAGE):
            try:
                stage = omni.usd.get_context().get_stage()
                if stage:
                    self._entity_registry.scan_stage(stage, capture_scope, "/World")
                    self._entity_registry.register_resync_listener(stage)
            except Exception:
                pass

        # API 세션 등록 (비동기, 실패해도 로컬 캡처는 계속)
        asyncio.ensure_future(self._register_session_api())

        # registry에서 physics prim을 PhysicsSampler에 일괄 등록
        if self._entity_registry.tracked_count > 0:
            self._physics_sampler.register_prims_from_registry(self._entity_registry)
        elif capture_scope in (CaptureScope.AUTO_DYNAMIC, CaptureScope.FULL_STAGE):
            # registry 스캔 실패 시 기존 방식 fallback
            self._register_physics_prims_from_stage()

        # 샘플러 시작
        try:
            self._physics_sampler.start(decimation=decimation)
        except Exception as e:
            # PhysX 구독 실패해도 USD watcher는 시작
            pass

        self._usd_watcher.start()
        self._is_active = True

        tracked = self._physics_sampler.tracked_prim_count
        print(f"[CaptureCoordinator] Session started: {self._simulation_id[:8]}... "
              f"scope={capture_scope.value}, tracked_prims={tracked}")

        return f"세션 시작: {self._simulation_id[:8]}... scope={capture_scope.value}"

    def stop_session(self) -> str:
        """캡처 세션 종료.

        1. 샘플러 중지
        2. 최종 flush
        3. API 세션 종료 (PATCH)
        """
        if not self._is_active:
            return "활성 세션 없음"

        self._is_active = False
        total = self._stats.get("total_deltas", 0)
        print(f"[CaptureCoordinator] Session stopping: total_deltas={total}")

        # 샘플러 중지
        self._physics_sampler.stop()
        self._usd_watcher.stop()
        self._entity_registry.stop()

        # Capture IDs before clearing (async coroutines need them later)
        sim_id = self._simulation_id
        total_deltas = self._stats.get("total_deltas", 0)

        # 최종 flush
        if self._buffer and self._api_url:
            asyncio.ensure_future(self.flush_buffer(self._api_url))

        # API 세션 종료 등록
        if self._api_url and sim_id:
            asyncio.ensure_future(self._close_session_api(sim_id, total_deltas))

        self._simulation_id = None
        self._session_id = None

        return f"세션 종료: {(sim_id or '')[:8]}..."

    def add_prim_to_scope(self, prim_path: str):
        """Scoped 모드에서 특정 prim을 캡처 대상에 추가.

        Stage API 호출 포함 → 메인 스레드에서 호출해야 함.
        """
        self._physics_sampler.register_prim(prim_path)

    # -- Delta 수집 ----------------------------------------------------------

    def add_delta(
        self,
        prim_path: str,
        property_name: str,
        value: Any,
        capture_source: str,
        delta_type: str = "property_changed",
    ):
        """PhysicsSampler / UsdChangeWatcher에서 delta 제출.

        sequence_id와 sim_step을 할당하고 버퍼에 append.
        thread-safe (복수 소스에서 동시 호출 가능).
        """
        if not self._is_active:
            return

        seq_id = self._next_sequence_id()
        sim_step = self._current_sim_step
        capture_time = datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat()

        entity_path = _extract_entity_path(prim_path)
        entity_id = str(uuid.uuid5(_ENTITY_NAMESPACE, entity_path)) if entity_path else ""

        delta = {
            "prim_path": prim_path,
            "property_name": property_name,
            "value_raw": value,  # json.dumps deferred to flush (PhysX callback safety)
            "capture_time": capture_time,
            "simulation_id": self._simulation_id or "",
            "entity_id": entity_id,
            "sequence_id": seq_id,
            "sim_step": sim_step,
            "capture_source": capture_source,
            "delta_type": delta_type,
        }

        with self._buffer_lock:
            self._buffer.append(delta)

        # 통계 갱신
        self._stats["total_deltas"] += 1
        if capture_source == "physics":
            self._stats["physics_deltas"] += 1
        else:
            self._stats["usd_notice_deltas"] += 1

        # Auto-flush 체크
        self._auto_flush_check()

    # -- Flush ---------------------------------------------------------------

    async def flush_buffer(self, api_url: str) -> tuple:
        """Snapshot-and-swap 패턴으로 버퍼를 API로 전송.

        Args:
            api_url: Lakehouse API base URL

        Returns:
            (count_sent, had_error, error_message)
        """
        if self._flush_in_flight:
            return (0, False, "flush 진행 중")

        with self._buffer_lock:
            if not self._buffer:
                return (0, False, "버퍼 비어있음")
            # Snapshot-and-swap
            snapshot = self._buffer
            self._buffer = []

        self._flush_in_flight = True
        try:
            # Deferred JSON serialization (moved out of PhysX callback path)
            for d in snapshot:
                if "value_raw" in d:
                    d["value_json"] = json.dumps(d.pop("value_raw"), default=str)

            batch_id = str(uuid.uuid4())
            # Derive simulation_id from first delta (safe even after stop_session clears self._simulation_id)
            batch_sim_id = self._simulation_id or (snapshot[0].get("simulation_id", "") if snapshot else "")
            payload = {
                "simulation_id": batch_sim_id,
                "batch_id": batch_id,
                "deltas": snapshot,
            }

            try:
                total_d = self._stats.get("total_deltas", 0)
                print(f"[CaptureCoordinator] Flushing {len(snapshot)} deltas "
                      f"(total so far: {total_d})")
                await api_post_json(api_url, "api/v1/realtime/flush", payload)
                self._last_flush_time = time.time()
                self._stats["total_flushes"] += 1
                print(f"[CaptureCoordinator] Flushed {len(snapshot)} deltas OK")
                return (len(snapshot), False, "")
            except Exception as e:
                print(f"[CaptureCoordinator] Flush failed ({e}), retrying in 5s...")
                # 1회 재시도 (5초 후)
                await asyncio.sleep(5)
                try:
                    await api_post_json(api_url, "api/v1/realtime/flush", payload)
                    self._last_flush_time = time.time()
                    self._stats["total_flushes"] += 1
                    print(f"[CaptureCoordinator] Retry flush OK ({len(snapshot)} deltas)")
                    return (len(snapshot), False, "")
                except Exception as e2:
                    # 실패 시 snapshot을 버퍼 앞에 복원
                    with self._buffer_lock:
                        self._buffer = snapshot + self._buffer
                    self._stats["flush_errors"] += 1
                    return (0, True, str(e2))
        finally:
            self._flush_in_flight = False

    def _auto_flush_check(self):
        """버퍼 크기 threshold 초과 시 자동 flush 트리거."""
        if (
            len(self._buffer) >= self._auto_flush_threshold
            and not self._flush_in_flight
            and (time.time() - self._last_flush_time) >= self._min_flush_interval
            and self._api_url
        ):
            try:
                asyncio.ensure_future(self.flush_buffer(self._api_url))
            except Exception:
                pass

    # -- Sequence ID ---------------------------------------------------------

    def _next_sequence_id(self) -> int:
        """Thread-safe 단조증가 sequence_id 반환."""
        with self._sequence_lock:
            self._sequence_counter += 1
            return self._sequence_counter

    # -- Internal Helpers ----------------------------------------------------

    def _register_physics_prims_from_stage(self):
        """Stage에서 PhysicsRigidBodyAPI가 적용된 prim을 자동 탐색 후 등록.

        Stage API 호출 → 메인 스레드에서 start_session() 시 호출됨.
        """
        try:
            stage = omni.usd.get_context().get_stage()
            if not stage:
                return

            from pxr import Usd, UsdPhysics

            for prim in stage.Traverse():
                if not prim.IsValid():
                    continue
                prim_path = str(prim.GetPath())

                # /World 하위만 대상
                if not prim_path.startswith("/World/"):
                    continue

                # PhysicsRigidBodyAPI 적용 여부 확인
                has_rigid_body = False
                try:
                    has_rigid_body = UsdPhysics.RigidBodyAPI(prim)
                except Exception:
                    # UsdPhysics 없거나 적용 안 된 prim
                    pass

                if has_rigid_body:
                    self._physics_sampler.register_prim(prim_path)

        except Exception:
            # Stage 탐색 실패 시 무시 — PhysicsSampler는 빈 tracked_prims로 동작
            pass

    async def _register_session_api(self):
        """Lakehouse API에 시뮬레이션 세션 등록 (POST /api/v1/simulation/sessions)."""
        if not self._api_url or not self._simulation_id:
            return
        try:
            payload = {
                "simulation_id": self._simulation_id,
                "scene_path": self._scene_path or "",
                "entity_count": (
                    self._entity_registry.tracked_count
                    if self._entity_registry and self._entity_registry.tracked_count > 0
                    else self._physics_sampler.tracked_prim_count
                ),
            }
            await api_post_json(self._api_url, "api/v1/simulation/sessions", payload)
        except Exception:
            # API 등록 실패해도 로컬 캡처는 계속 진행
            pass

    async def _close_session_api(self, sim_id: str, total_deltas: int):
        """Lakehouse API에 세션 종료 신호 (PATCH /api/v1/simulation/sessions/{id}).

        Args:
            sim_id: 종료할 simulation_id (stop_session에서 캡처)
            total_deltas: 최종 delta 수 (stop_session에서 캡처)
        """
        if not self._api_url or not sim_id:
            return
        try:
            end_time = datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat()
            payload = {
                "status": "completed",
                "end_time": end_time,
                "total_deltas": total_deltas,
            }
            # PATCH: endpoint에 simulation_id 포함
            loop = asyncio.get_running_loop()
            import urllib.request

            url = f"{self._api_url.rstrip('/')}/api/v1/simulation/sessions/{sim_id}"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="PATCH",
            )
            await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=10).read()
            )
        except Exception:
            # 세션 종료 신호 실패는 무시
            pass

    # -- Cleanup -------------------------------------------------------------

    def cleanup(self):
        """전체 정리: 샘플러 중지, 버퍼 초기화."""
        if self._is_active:
            self.stop_session()
        self._physics_sampler.stop()
        self._usd_watcher.stop()
        self._entity_registry.clear()
        self._authority_map.clear()
        with self._buffer_lock:
            self._buffer.clear()


# =====================================================================
#  공용 헬퍼
# =====================================================================

def _extract_entity_path(prim_path: str) -> str:
    """prim 경로에서 entity 경로 추출: /World/XXX/... -> /World/XXX."""
    parts = prim_path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "World":
        return f"/World/{parts[1]}"
    return ""
