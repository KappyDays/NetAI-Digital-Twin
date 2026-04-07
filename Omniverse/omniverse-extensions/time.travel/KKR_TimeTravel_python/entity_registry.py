"""Entity Registry — Prim 분류 및 캐시된 핸들 관리.

세션 시작 시 Stage 스캔 → Prim 분류 (physics_driven/script_driven/static)
런타임 Prim 생성/삭제 시 Tf.Notice.GetResyncedPaths()로 증분 업데이트.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .capture_coordinator import CaptureScope

# 물리 속성 이름 목록 (PhysicsSampler와 동일)
_PHYSICS_ATTRS = [
    "xformOp:translate",
    "xformOp:orient",
    "xformOp:scale",
    "physics:velocity",
    "physics:angularVelocity",
]

# xformOp 계열 속성 prefix — script_driven 판별용
_XFORM_OP_PREFIX = "xformOp:"


class PrimInfo:
    """캐시된 Prim 정보."""

    __slots__ = ("path", "classification", "attr_handles")

    def __init__(
        self,
        path: str,
        classification: str,
        attr_handles: dict[str, Any],
    ):
        self.path = path
        self.classification = classification  # "physics_driven" | "script_driven" | "static"
        self.attr_handles = attr_handles      # {attr_name: Usd.Attribute}

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "classification": self.classification,
            "attr_handles": self.attr_handles,
        }


class EntityRegistry:
    """Stage Prim 분류 레지스트리.

    Usage:
        registry = EntityRegistry()
        count = registry.scan_stage(stage, capture_scope, scope_root="/World")
        registry.register_resync_listener(stage)
        physics_paths = registry.get_physics_prims()
        # ... 세션 종료 시 ...
        registry.stop()
        registry.clear()
    """

    def __init__(self):
        # prim_path → PrimInfo
        self._tracked: dict[str, PrimInfo] = {}
        # Tf.Notice 리스너 핸들
        self._resync_listener = None
        self._stage_ref = None  # 약한 참조용 (리스너 취소 시 사용)

    # -- 스캔 -------------------------------------------------------------------

    def scan_stage(self, stage, scope, scope_root: str = "/World") -> int:
        """Stage를 스캔하여 /World 하위 Prim을 분류·캐시.

        Args:
            stage:      Usd.Stage 인스턴스
            scope:      CaptureScope enum (SCOPED 모드에서 scope_root 우선 적용)
            scope_root: 탐색 기준 경로 (기본 /World)

        Returns:
            등록된 Prim 수
        """
        if stage is None:
            return 0

        self._stage_ref = stage

        try:
            from pxr import Usd, UsdPhysics

            root_prim = stage.GetPrimAtPath(scope_root)
            if not root_prim or not root_prim.IsValid():
                # scope_root가 없으면 전체 Traverse fallback
                prims_iter = stage.Traverse()
            else:
                # scope_root 하위만 순회 (PreAndPostVisit 없이 기본 순회)
                prims_iter = Usd.PrimRange(root_prim)

            for prim in prims_iter:
                if not prim.IsValid():
                    continue
                prim_path = str(prim.GetPath())

                # /World 직계 자식 이상만 (scope_root == "/World" 이면 /World 자체 제외)
                if prim_path == scope_root:
                    continue
                if not prim_path.startswith(scope_root + "/"):
                    continue

                classification = self.classify_prim(prim)

                # attr handle 캐싱 (physics_driven만 물리 속성 캐싱, 나머지는 빈 dict)
                attr_handles: dict[str, Any] = {}
                if classification == "physics_driven":
                    for attr_name in _PHYSICS_ATTRS:
                        attr = prim.GetAttribute(attr_name)
                        if attr.IsValid():
                            attr_handles[attr_name] = attr

                self._tracked[prim_path] = PrimInfo(
                    path=prim_path,
                    classification=classification,
                    attr_handles=attr_handles,
                )

        except Exception:
            # Stage 탐색 실패 시 빈 레지스트리로 계속
            pass

        return len(self._tracked)

    # -- 분류 -------------------------------------------------------------------

    def classify_prim(self, prim) -> str:
        """Prim을 분류.

        Args:
            prim: Usd.Prim 인스턴스

        Returns:
            "physics_driven" | "script_driven" | "static"
        """
        try:
            from pxr import UsdPhysics

            # PhysicsRigidBodyAPI 또는 ArticulationRootAPI → physics_driven
            if UsdPhysics.RigidBodyAPI(prim) or UsdPhysics.ArticulationRootAPI(prim):
                return "physics_driven"
        except Exception:
            pass

        try:
            # xformOp 계열 속성 존재 → script_driven (스크립트/애니메이션으로 움직임)
            for prop in prim.GetProperties():
                if prop.GetName().startswith(_XFORM_OP_PREFIX):
                    return "script_driven"
        except Exception:
            pass

        return "static"

    # -- Resync 리스너 ----------------------------------------------------------

    def register_resync_listener(self, stage):
        """Tf.Notice.ObjectsChanged 리스너 등록 — Prim 추가/삭제 감지.

        Stage API 포함 → 메인 스레드에서 호출해야 함.
        """
        self._stage_ref = stage
        try:
            from pxr import Tf, Usd

            self._resync_listener = Tf.Notice.Register(
                Usd.Notice.ObjectsChanged,
                self._on_resync,
                stage,
            )
        except Exception:
            self._resync_listener = None

    def _on_resync(self, notice, sender):
        """ObjectsChanged 콜백 — 새 Prim 등록 / 삭제된 Prim 제거."""
        try:
            stage = self._stage_ref
            if stage is None:
                return

            for path in notice.GetResyncedPaths():
                prim_path = str(path)

                prim = stage.GetPrimAtPath(path)
                if prim and prim.IsValid():
                    # 신규 또는 변경된 Prim — 재분류·재캐싱
                    if prim_path not in self._tracked:
                        from pxr import UsdPhysics
                        classification = self.classify_prim(prim)
                        attr_handles: dict[str, Any] = {}
                        if classification == "physics_driven":
                            for attr_name in _PHYSICS_ATTRS:
                                attr = prim.GetAttribute(attr_name)
                                if attr.IsValid():
                                    attr_handles[attr_name] = attr
                        self._tracked[prim_path] = PrimInfo(
                            path=prim_path,
                            classification=classification,
                            attr_handles=attr_handles,
                        )
                else:
                    # 삭제된 Prim — 레지스트리에서 제거
                    self._tracked.pop(prim_path, None)

        except Exception:
            pass

    # -- 조회 -------------------------------------------------------------------

    def get_tracked_prims(self) -> list[str]:
        """추적 중인 모든 Prim 경로 반환."""
        return list(self._tracked.keys())

    def get_physics_prims(self) -> list[str]:
        """physics_driven Prim 경로만 반환."""
        return [
            path
            for path, info in self._tracked.items()
            if info.classification == "physics_driven"
        ]

    def get_prim_info(self, prim_path: str) -> Optional[dict]:
        """특정 Prim의 분류 정보와 attr_handles 반환."""
        info = self._tracked.get(prim_path)
        if info is None:
            return None
        return info.to_dict()

    def get_prim_info_obj(self, prim_path: str) -> Optional[PrimInfo]:
        """PrimInfo 객체 직접 반환 (PhysicsSampler 연동용)."""
        return self._tracked.get(prim_path)

    @property
    def tracked_count(self) -> int:
        return len(self._tracked)

    # -- 정리 -------------------------------------------------------------------

    def stop(self):
        """Tf.Notice 리스너 해제."""
        if self._resync_listener is not None:
            try:
                self._resync_listener.Revoke()
            except Exception:
                pass
            self._resync_listener = None

    def clear(self):
        """레지스트리 전체 초기화."""
        self.stop()
        self._tracked.clear()
        self._stage_ref = None
