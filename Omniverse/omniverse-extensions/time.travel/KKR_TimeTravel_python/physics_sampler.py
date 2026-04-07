"""Physics Sampler — PhysX 콜백 기반 물리 상태 캡처.

`omni.physx.get_physx_interface().subscribe_physics_step_events()` 를 통해
매 물리 스텝마다 등록된 prim의 물리 속성을 읽고, decimation 적용 후
CaptureCoordinator 버퍼에 delta를 제출.

핵심 제약:
  - 콜백(_on_physics_step) 내에서 JSON 직렬화, 네트워크 호출, Stage traversal 금지
  - cached prim attribute handle에서 값 읽기만 수행
  - Stage API는 메인 스레드에서만 호출되므로 콜백 내부는 안전
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import omni.usd

if TYPE_CHECKING:
    from .capture_coordinator import CaptureCoordinator

# 물리 속성 이름 목록 — prim 등록 시 읽어들일 대상
_PHYSICS_ATTRS = [
    "xformOp:translate",
    "xformOp:orient",
    "xformOp:scale",
    "physics:velocity",
    "physics:angularVelocity",
]


class PhysicsSampler:
    """PhysX 스텝 콜백 기반 물리 속성 샘플러.

    Usage:
        sampler = PhysicsSampler(coordinator)
        sampler.start(decimation=6)
        # ... 시뮬레이션 진행 ...
        sampler.stop()
    """

    def __init__(self, coordinator: "CaptureCoordinator"):
        self._coordinator = coordinator
        self._subscription = None   # subscribe 핸들 (언구독 시 사용)
        self._step_count: int = 0
        self._decimation: int = 6
        # [(prim_path, [(attr_name, attr_handle), ...])]
        self._tracked_prims: list[tuple[str, list[tuple[str, Any]]]] = []
        # 마지막 캡처 값 캐시 (dedup)
        self._last_values: dict[str, Any] = {}

    # -- Public API ----------------------------------------------------------

    def start(self, decimation: int = 6):
        """PhysX 스텝 이벤트 구독 시작.

        Args:
            decimation: N 스텝당 1회 캡처 (기본 6)
        """
        if self._subscription is not None:
            return  # 이미 구독 중

        self._decimation = max(1, decimation)
        self._step_count = 0
        self._last_values.clear()

        try:
            import omni.physx
            physx = omni.physx.get_physx_interface()
            self._subscription = physx.subscribe_physics_step_events(self._on_physics_step)
            print(f"[PhysicsSampler] Started: decimation={self._decimation}, "
                  f"tracked_prims={len(self._tracked_prims)}")
        except Exception as e:
            self._subscription = None
            print(f"[PhysicsSampler] PhysX subscription FAILED: {e}")
            raise RuntimeError(f"PhysX 구독 실패: {e}") from e

    def stop(self):
        """PhysX 스텝 이벤트 구독 해제."""
        if self._subscription is not None:
            try:
                self._subscription.unsubscribe()
            except Exception:
                try:
                    self._subscription()  # callable cleanup handle 패턴
                except Exception:
                    pass
            self._subscription = None
        self._step_count = 0

    def register_prim(self, prim_path: str):
        """물리 샘플링 대상 prim 등록. Stage에서 attribute handle을 캐싱.

        Stage API 호출이 포함되므로 메인 스레드에서 호출해야 함.
        """
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            return

        attr_handles = []
        for attr_name in _PHYSICS_ATTRS:
            attr = prim.GetAttribute(attr_name)
            if attr.IsValid():
                attr_handles.append((attr_name, attr))

        if attr_handles:
            # 중복 등록 방지
            existing_paths = {p for p, _ in self._tracked_prims}
            if prim_path not in existing_paths:
                self._tracked_prims.append((prim_path, attr_handles))
                # PropertyAuthorityMap에 등록
                self._coordinator.authority_map.register_physics_prim(
                    prim_path,
                    [name for name, _ in attr_handles]
                )
                print(f"[PhysicsSampler] Registered: {prim_path} "
                      f"({len(attr_handles)} attrs)")

    def unregister_prim(self, prim_path: str):
        """prim 샘플링 등록 해제."""
        self._tracked_prims = [
            (p, attrs) for p, attrs in self._tracked_prims if p != prim_path
        ]
        self._coordinator.authority_map.unregister_prim(prim_path)
        # 관련 dedup 캐시 제거
        keys_to_del = [k for k in self._last_values if k.startswith(f"{prim_path}.")]
        for k in keys_to_del:
            del self._last_values[k]

    def register_prims_from_registry(self, registry: "EntityRegistry"):
        """EntityRegistry에서 physics_driven prim을 일괄 등록.

        레지스트리가 이미 attr handle을 캐싱해 두었으므로
        Stage 재탐색 없이 핸들 배열을 직접 이관.

        메인 스레드에서 호출해야 함 (Stage API 보호).
        """
        from .entity_registry import EntityRegistry as _EntityRegistry

        existing_paths = {p for p, _ in self._tracked_prims}

        for prim_path in registry.get_physics_prims():
            if prim_path in existing_paths:
                continue

            info = registry.get_prim_info_obj(prim_path)
            if info is None or not info.attr_handles:
                continue

            # [(attr_name, attr_handle), ...] 형식으로 변환
            attr_list = list(info.attr_handles.items())
            self._tracked_prims.append((prim_path, attr_list))
            existing_paths.add(prim_path)

            # PropertyAuthorityMap 등록
            self._coordinator.authority_map.register_physics_prim(
                prim_path,
                list(info.attr_handles.keys()),
            )

    def clear_prims(self):
        """등록된 prim 전체 해제."""
        self._tracked_prims.clear()
        self._last_values.clear()

    @property
    def is_active(self) -> bool:
        return self._subscription is not None

    @property
    def tracked_prim_count(self) -> int:
        return len(self._tracked_prims)

    @property
    def step_count(self) -> int:
        return self._step_count

    # -- PhysX Callback ------------------------------------------------------

    def _on_physics_step(self, dt: float):
        """PhysX 매 스텝마다 호출되는 콜백.

        CRITICAL 제약:
          - JSON 직렬화 금지
          - 네트워크 호출 금지
          - Stage traversal 금지 (GetChildren 등)
          - 오직 캐싱된 attr handle의 .Get() 만 허용
        """
        self._step_count += 1

        # Decimation: N 스텝당 1회만 캡처
        if self._step_count % self._decimation != 0:
            return

        for prim_path, attr_handles in self._tracked_prims:
            for attr_name, attr in attr_handles:
                try:
                    val = attr.Get()
                    if val is None:
                        continue

                    # 단순값 변환 (콜백 내에서는 경량 변환만 허용)
                    simple_val = _to_simple_value_fast(val)

                    # 값 dedup
                    dedup_key = f"{prim_path}.{attr_name}"
                    if self._last_values.get(dedup_key) == simple_val:
                        continue
                    self._last_values[dedup_key] = simple_val

                    # Coordinator에 delta 제출 (버퍼 append만 수행)
                    self._coordinator.add_delta(
                        prim_path=prim_path,
                        property_name=attr_name,
                        value=simple_val,
                        capture_source="physics",
                    )
                except Exception:
                    # 콜백 내 예외는 무시 (시뮬레이션 중단 방지)
                    pass


# =====================================================================
#  경량 값 변환 — 콜백 내 전용 (JSON/네트워크 없음)
# =====================================================================

def _to_simple_value_fast(val) -> Any:
    """USD 값을 Python 기본 타입으로 변환. 콜백 내 경량 버전."""
    if val is None:
        return None
    if isinstance(val, (bool, int, float, str)):
        return val
    # Quaternion (GfQuatf / GfQuatd)
    if hasattr(val, "GetReal") and hasattr(val, "GetImaginary"):
        imag = val.GetImaginary()
        return [float(val.GetReal()), float(imag[0]), float(imag[1]), float(imag[2])]
    # Vec3 / 배열형
    if hasattr(val, "__len__"):
        try:
            return [float(v) for v in val]
        except (TypeError, ValueError):
            return str(val)
    return str(val)
