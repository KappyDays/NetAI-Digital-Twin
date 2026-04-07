"""Property Authority Map — 속성 경로 수준 소유권 판정.

4-Pipeline 캡처 아키텍처에서 PhysicsSampler와 UsdChangeWatcher의
중복 캡처를 방지하기 위해 각 prim+property 쌍에 대한 소유권을 추적.

Physics 속성: PhysicsSampler 소유 (PhysX 콜백으로 캡처)
비물리 속성: UsdChangeWatcher 소유 (Tf.Notice로 캡처)
"""

# 물리 시뮬레이션 결과로 간주되는 속성 이름 집합 (PhysicsSampler 소유)
_PHYSICS_PROPERTY_NAMES = frozenset({
    "xformOp:translate",
    "xformOp:orient",
    "xformOp:scale",
    "physics:velocity",
    "physics:angularVelocity",
})

_OWNER_PHYSICS = "physics"
_OWNER_USD_NOTICE = "usd_notice"
_OWNER_UNOWNED = "unowned"


class PropertyAuthorityMap:
    """속성 경로 수준 소유권 판정기.

    Usage:
        authority_map = PropertyAuthorityMap()
        authority_map.register_physics_prim("/World/Robot", ["xformOp:translate"])
        owner = authority_map.get_owner("/World/Robot", "xformOp:translate")  # "physics"
    """

    def __init__(self):
        # {prim_path: set(property_name)} — PhysicsSampler 소유 목록
        self._physics_owned: dict[str, set] = {}

    def register_physics_prim(self, prim_path: str, physics_properties: list[str]):
        """PhysicsSampler 소유 속성 목록 등록.

        Args:
            prim_path: Prim 경로 (예: "/World/Robot")
            physics_properties: 해당 prim에서 PhysicsSampler가 담당할 속성 이름 목록
        """
        owned = self._physics_owned.setdefault(prim_path, set())
        owned.update(physics_properties)

    def register_rigid_body(self, prim_path: str):
        """PhysicsRigidBodyAPI가 적용된 prim을 등록 — 표준 물리 속성 전체를 physics 소유로 마킹."""
        self.register_physics_prim(prim_path, list(_PHYSICS_PROPERTY_NAMES))

    def unregister_prim(self, prim_path: str):
        """Prim 등록 해제 (예: 시뮬레이션 중 prim 삭제 시)."""
        self._physics_owned.pop(prim_path, None)

    def clear(self):
        """모든 소유권 정보 초기화 (세션 종료 시)."""
        self._physics_owned.clear()

    def get_owner(self, prim_path: str, property_name: str) -> str:
        """속성의 소유 파이프라인을 반환.

        Returns:
            "physics"    — PhysicsSampler 소유
            "usd_notice" — UsdChangeWatcher 소유
            "unowned"    — 미등록 속성
        """
        prim_props = self._physics_owned.get(prim_path)
        if prim_props is not None and property_name in prim_props:
            return _OWNER_PHYSICS

        # 전역 물리 속성 이름 규칙 체크 (명시적 등록 없어도 physics 소유)
        if property_name in _PHYSICS_PROPERTY_NAMES and prim_path in self._physics_owned:
            return _OWNER_PHYSICS

        # prim이 physics로 등록되어 있으면 물리 속성은 physics 소유
        if prim_path in self._physics_owned and property_name in _PHYSICS_PROPERTY_NAMES:
            return _OWNER_PHYSICS

        if prim_path in self._physics_owned:
            # 등록된 prim이지만 physics 소유 속성이 아님 → usd_notice
            return _OWNER_USD_NOTICE

        return _OWNER_UNOWNED

    def is_physics_owned(self, prim_path: str, property_name: str) -> bool:
        """속성이 PhysicsSampler 소유인지 확인."""
        return self.get_owner(prim_path, property_name) == _OWNER_PHYSICS

    @property
    def registered_prim_count(self) -> int:
        return len(self._physics_owned)

    def registered_prims(self) -> list[str]:
        return list(self._physics_owned.keys())
