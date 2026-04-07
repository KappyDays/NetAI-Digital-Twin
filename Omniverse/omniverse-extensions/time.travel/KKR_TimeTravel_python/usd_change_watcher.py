"""USD Change Watcher — Tf.Notice 기반 비물리 속성 변경 캡처.

PhysicsSampler가 담당하지 않는 비물리 속성 (visibility, material, custom attributes 등)을
`Usd.Notice.ObjectsChanged`로 감지하여 CaptureCoordinator 버퍼에 delta 제출.

필터링 규칙:
  - Timeline Gating: is_playing() 아니면 무시
  - Path Blacklist: gui:*, editor:*, /Render*, /Render/* 경로 무시
  - Session Layer 제외: session layer 변경은 무시
  - Property Authority: PhysicsSampler 소유 속성 무시
  - Value Dedup: 마지막 캡처값과 동일하면 무시
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import omni.timeline
import omni.usd
from pxr import Tf, Usd

if TYPE_CHECKING:
    from .capture_coordinator import CaptureCoordinator

# Path Blacklist 접두사 목록
_PATH_BLACKLIST_PREFIXES = (
    "gui:",
    "editor:",
    "/Render",
)

# 최소 캡처 간격 (초) — notice storm 방지
_MIN_CAPTURE_INTERVAL = 0.05


class UsdChangeWatcher:
    """Tf.Notice.ObjectsChanged 기반 비물리 속성 변경 감시자.

    Usage:
        watcher = UsdChangeWatcher(coordinator)
        watcher.start()
        # ... 시뮬레이션 진행 ...
        watcher.stop()
    """

    def __init__(self, coordinator: "CaptureCoordinator"):
        self._coordinator = coordinator
        self._listener = None
        self._active = False

        # 마지막 캡처 값 (dedup)
        self._last_values: dict[str, Any] = {}
        # 마지막 캡처 시각 (rate limiting)
        self._last_capture_times: dict[str, float] = {}

    # -- Public API ----------------------------------------------------------

    def start(self):
        """Tf.Notice.ObjectsChanged 리스너 등록."""
        if self._active:
            return

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        self._active = True
        self._last_values.clear()
        self._last_capture_times.clear()

        try:
            self._listener = Tf.Notice.Register(
                Usd.Notice.ObjectsChanged,
                self._on_objects_changed,
                stage,
            )
        except Exception as e:
            self._active = False
            raise RuntimeError(f"Tf.Notice 등록 실패: {e}") from e

    def stop(self):
        """Tf.Notice 리스너 해제."""
        self._active = False
        if self._listener:
            try:
                self._listener.Revoke()
            except Exception:
                pass
            self._listener = None

    @property
    def is_active(self) -> bool:
        return self._active

    def clear_state(self):
        """dedup 상태 초기화 (세션 재시작 시)."""
        self._last_values.clear()
        self._last_capture_times.clear()

    # -- Tf.Notice Callback --------------------------------------------------

    def _on_objects_changed(self, notice, sender):
        """Tf.Notice 콜백 — 비물리 속성 변경을 캡처.

        메인 스레드에서 호출되므로 Stage API 호출 안전.
        """
        if not self._active:
            return

        # Timeline Gating: 재생 중일 때만 캡처
        try:
            if not omni.timeline.get_timeline_interface().is_playing():
                return
        except Exception:
            pass

        capture_time = time.time()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        # Session Layer 식별 — session layer의 변경은 무시
        session_layer = stage.GetSessionLayer()

        for path in notice.GetChangedInfoOnlyPaths():
            try:
                path_str = str(path)

                # Path Blacklist 체크
                if _is_blacklisted(path_str):
                    continue

                # Property path 파싱
                if hasattr(path, "IsPropertyPath") and path.IsPropertyPath():
                    prim_path_str = str(path.GetPrimPath())
                    prop_name = path.name
                else:
                    # 문자열 파싱 fallback
                    if "." in path_str:
                        prim_path_str, prop_name = path_str.rsplit(".", 1)
                    else:
                        continue

                # Session Layer 제외 — session layer에서 온 변경인지 확인
                if session_layer and _is_session_layer_change(stage, session_layer, prim_path_str, prop_name):
                    continue

                # Property Authority 체크 — PhysicsSampler 소유 속성은 무시
                if self._coordinator.authority_map.is_physics_owned(prim_path_str, prop_name):
                    continue

                # Rate limiting
                dedup_key = f"{prim_path_str}.{prop_name}"
                last_time = self._last_capture_times.get(dedup_key, 0.0)
                if (capture_time - last_time) < _MIN_CAPTURE_INTERVAL:
                    continue

                # 현재 값 읽기
                prim = stage.GetPrimAtPath(prim_path_str)
                if not prim.IsValid():
                    continue

                attr = prim.GetAttribute(prop_name)
                if not attr.IsValid():
                    continue

                val = attr.Get()
                simple_val = _to_simple_value(val)

                # Value Dedup
                if simple_val == self._last_values.get(dedup_key):
                    continue

                self._last_capture_times[dedup_key] = capture_time
                self._last_values[dedup_key] = simple_val

                # Coordinator에 delta 제출
                self._coordinator.add_delta(
                    prim_path=prim_path_str,
                    property_name=prop_name,
                    value=simple_val,
                    capture_source="usd_notice",
                    delta_type="property_changed",
                )

            except Exception:
                # notice 처리 중 예외는 무시 (다음 속성 계속 처리)
                continue


# =====================================================================
#  내부 헬퍼
# =====================================================================

def _is_blacklisted(path_str: str) -> bool:
    """Path Blacklist 규칙에 해당하는지 확인."""
    for prefix in _PATH_BLACKLIST_PREFIXES:
        if path_str.startswith(prefix):
            return True
    # 속성 경로의 prim 부분이 /Render로 시작하는 경우
    if "." in path_str:
        prim_part = path_str.rsplit(".", 1)[0]
        if prim_part.startswith("/Render"):
            return True
    return False


def _is_session_layer_change(stage, session_layer, prim_path_str: str, prop_name: str) -> bool:
    """변경이 session layer에서만 발생한 것인지 확인."""
    try:
        from pxr import Sdf
        prim_spec = session_layer.GetPrimAtPath(prim_path_str)
        if prim_spec and prim_spec.GetAttributeAtPath(
            Sdf.Path(f"{prim_path_str}.{prop_name}")
        ):
            # session layer에 해당 속성이 있으면 session layer 변경으로 간주
            return True
    except Exception:
        pass
    return False


def _to_simple_value(val) -> Any:
    """USD 값을 Python 기본 타입으로 변환."""
    if val is None:
        return None
    if isinstance(val, (bool, int, float, str)):
        return val
    # Quaternion
    if hasattr(val, "GetReal") and hasattr(val, "GetImaginary"):
        imag = val.GetImaginary()
        return [float(val.GetReal()), float(imag[0]), float(imag[1]), float(imag[2])]
    # Vector / 배열형
    if hasattr(val, "__len__"):
        try:
            return [float(v) for v in val]
        except (TypeError, ValueError):
            return str(val)
    return str(val)


def _extract_entity_path(prim_path: str) -> str:
    """prim 경로에서 entity 경로 추출: /World/XXX/... -> /World/XXX."""
    parts = prim_path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "World":
        return f"/World/{parts[1]}"
    return ""
