"""Timeline Baker — 시뮬레이션 delta를 USD TimeSamples로 베이킹.

Lakehouse에서 delta bulk query → 익명 Sdf.Layer에 timeSamples 기록
→ sublayer로 추가 → Animation Timeline 네이티브 재생.

Key design:
  - 청크 단위 비동기 베이킹 (UI 프리징 방지)
  - next_update_async() per chunk for UI responsiveness
  - 취소 지원 (cancel_event)
"""

import json
import threading
from datetime import datetime
from typing import Any, Callable, Optional

import omni.kit.app
import omni.timeline
import omni.usd
from pxr import Gf, Sdf

from .api_client import api_get

# Yield to UI every N deltas to prevent frame freeze
_CHUNK_SIZE = 200


class TimelineBaker:
    """시뮬레이션 delta를 USD TimeSamples로 베이킹하는 클래스.

    Usage:
        baker = TimelineBaker()
        await baker.bake_session(simulation_id, api_url, fps=60,
                                 on_progress=lambda cur, total: ...)
        # ... Animation Timeline에서 재생 ...
        baker.remove_replay_layer()
    """

    def __init__(self):
        self._replay_layer: Optional[Sdf.Layer] = None
        self._replay_layer_id: Optional[str] = None
        self._is_baking: bool = False
        self._cancel_event = threading.Event()
        self._baked_fps: float = 60.0
        self._baked_frame_count: int = 0
        self._pre_bake_timeline: Optional[dict] = None

    # -- Properties ----------------------------------------------------------

    @property
    def is_replay_active(self) -> bool:
        """sublayer가 Stage에 추가된 상태 여부."""
        return self._replay_layer is not None

    @property
    def is_baking(self) -> bool:
        """bake_session 진행 중 여부."""
        return self._is_baking

    @property
    def baked_frame_count(self) -> int:
        """마지막 bake의 총 프레임 수."""
        return self._baked_frame_count

    # -- Public API ----------------------------------------------------------

    def cancel_bake(self):
        """진행 중인 bake를 취소 요청. 다음 청크 경계에서 중단됨."""
        self._cancel_event.set()

    async def bake_session(
        self,
        simulation_id: str,
        api_url: str,
        fps: float = 0.0,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> Optional[Sdf.Layer]:
        """Lakehouse delta → 익명 Sdf.Layer timeSamples 베이킹 후 sublayer 추가.

        Args:
            simulation_id: 대상 시뮬레이션 ID
            api_url: Lakehouse API base URL
            fps: 초당 프레임 수 (0이면 Stage의 timeCodesPerSecond 사용)
            on_progress: 진행률 콜백 (current_idx, total)

        Returns:
            생성된 Sdf.Layer (취소/실패 시 None)
        """
        self._is_baking = True
        self._cancel_event.clear()

        try:
            # 1. Delta 전체 수집 (페이지네이션)
            all_deltas = []
            offset = 0
            page_size = 10000
            while True:
                if self._cancel_event.is_set():
                    return None
                url_params = (
                    f"simulation_id={simulation_id}"
                    f"&limit={page_size}"
                    f"&offset={offset}"
                )
                result = await api_get(api_url, f"api/v1/simulation/deltas?{url_params}")
                deltas = result.get("deltas", [])
                if not deltas:
                    break
                all_deltas.extend(deltas)
                offset += page_size
                if len(deltas) < page_size:
                    break

            if not all_deltas:
                return None

            # 2. Stage fps 결정 (사용자 지정 > Stage > 기본값 60)
            if fps <= 0:
                stage = omni.usd.get_context().get_stage()
                if stage and stage.GetTimeCodesPerSecond() > 0:
                    fps = stage.GetTimeCodesPerSecond()
                else:
                    fps = 60.0
            self._baked_fps = fps

            # 3. sequence_id 순 정렬
            all_deltas.sort(key=lambda d: d.get("sequence_id", 0))

            # 4. 시간축 기준점 계산 (첫/마지막 delta의 capture_time)
            # 파싱 실패한 delta는 건너뛰고 유효한 시간 범위를 찾음
            t_min = 0.0
            t_max = 0.0
            for d in all_deltas:
                t = _parse_capture_time(d.get("capture_time", ""))
                if t > 0:
                    t_min = t
                    break
            for d in reversed(all_deltas):
                t = _parse_capture_time(d.get("capture_time", ""))
                if t > 0:
                    t_max = t
                    break
            if t_min <= 0:
                # 모든 capture_time 파싱 실패 — sequence_id 기반 fallback
                t_min = 0.0
                t_max = len(all_deltas) / fps

            # 4. 익명 레이어 생성 (thread-safe)
            layer = Sdf.Layer.CreateAnonymous("replay_bake.usda")

            # 5. 청크 단위로 timeSamples 베이킹
            total = len(all_deltas)
            for i, delta in enumerate(all_deltas):
                if self._cancel_event.is_set():
                    return None

                prim_path = delta.get("prim_path", "")
                prop_name = delta.get("property_name", "")
                value_json = delta.get("value_json", "null")
                capture_time_str = delta.get("capture_time", "")

                value = _parse_value_json(value_json)
                if prim_path and prop_name and value is not None:
                    frame = _compute_frame(capture_time_str, t_min, fps)
                    try:
                        _write_time_sample(layer, prim_path, prop_name, frame, value)
                    except Exception:
                        pass

                # 청크 경계마다 UI에 양보
                if i % _CHUNK_SIZE == 0:
                    if on_progress:
                        on_progress(i, total)
                    await omni.kit.app.get_app().next_update_async()

            if on_progress:
                on_progress(total, total)

            # 6. 최대 프레임 계산 — t_max 기반 (정확한 캡처 구간)
            max_frame = (t_max - t_min) * fps if t_max > t_min else 0.0
            self._baked_frame_count = int(max_frame) + 1

            # 7. Stage sublayer에 추가 (메인 스레드, Stage API)
            stage = omni.usd.get_context().get_stage()
            if stage:
                root_layer = stage.GetRootLayer()
                root_layer.subLayerPaths.append(layer.identifier)
                self._replay_layer = layer
                self._replay_layer_id = layer.identifier

            # 8. Animation Timeline 범위를 베이킹된 프레임에 맞춤
            try:
                timeline = omni.timeline.get_timeline_interface()
                # Save original timeline state before overwriting (only on first bake)
                if self._pre_bake_timeline is None:
                    self._pre_bake_timeline = {
                        "start_time": timeline.get_start_time(),
                        "end_time": timeline.get_end_time(),
                        "current_time": timeline.get_current_time(),
                        "start_timeCode": stage.GetStartTimeCode() if stage else 0.0,
                        "end_timeCode": stage.GetEndTimeCode() if stage else 0.0,
                        "timeCodesPerSecond": stage.GetTimeCodesPerSecond() if stage else 24.0,
                    }
                end_time = max_frame / fps if fps > 0 else max_frame / 60.0
                timeline.set_start_time(0.0)
                timeline.set_end_time(end_time)
                timeline.set_current_time(0.0)
                # 타임코드도 설정 (USD stage)
                if stage:
                    stage.SetStartTimeCode(0.0)
                    stage.SetEndTimeCode(max_frame)
                    stage.SetTimeCodesPerSecond(fps)
                print(f"[TimelineBaker] Timeline set: 0 ~ {max_frame:.0f} frames "
                      f"({end_time:.1f}s at {fps}fps), {total} deltas baked")
            except Exception as e:
                print(f"[TimelineBaker] Timeline range set failed: {e}")

            return layer

        finally:
            self._is_baking = False

    def remove_replay_layer(self):
        """베이킹 레이어를 Stage sublayer에서 제거."""
        if not self._replay_layer_id:
            return

        stage = omni.usd.get_context().get_stage()
        if stage:
            root_layer = stage.GetRootLayer()
            sub_paths = root_layer.subLayerPaths
            if self._replay_layer_id in sub_paths:
                idx = list(sub_paths).index(self._replay_layer_id)
                del sub_paths[idx]

        self._replay_layer = None
        self._replay_layer_id = None

    def restore_timeline(self):
        """Remove replay sublayer AND restore original timeline range.

        Combines remove_replay_layer() with timeline state restoration
        to fully revert the Stage to pre-bake state.
        """
        self.remove_replay_layer()
        if not self._pre_bake_timeline:
            return
        try:
            # Release physics objects before stopping to avoid tensor view warning
            try:
                import omni.physx
                omni.physx.get_physx_interface().release_physics_objects()
            except Exception:
                pass
            timeline = omni.timeline.get_timeline_interface()
            timeline.stop()
            timeline.set_start_time(self._pre_bake_timeline["start_time"])
            timeline.set_end_time(self._pre_bake_timeline["end_time"])
            timeline.set_current_time(self._pre_bake_timeline["current_time"])
            stage = omni.usd.get_context().get_stage()
            if stage:
                stage.SetStartTimeCode(self._pre_bake_timeline["start_timeCode"])
                stage.SetEndTimeCode(self._pre_bake_timeline["end_timeCode"])
                stage.SetTimeCodesPerSecond(self._pre_bake_timeline["timeCodesPerSecond"])
        except Exception as e:
            print(f"[TimelineBaker] Timeline restore failed: {e}")
        # TODO (Q2-3): Physics-free replay 상태 복원.
        # bake 시 물리 비활성화(physx.force_load_physics_from_usd)를 수행하는데,
        # 이 메서드에서 물리 상태도 함께 복원해야 함. 추후 설계 필요.
        self._pre_bake_timeline = None


# =====================================================================
#  내부 헬퍼
# =====================================================================

def _write_time_sample(
    layer: Sdf.Layer,
    prim_path: str,
    prop_name: str,
    frame: float,
    value: Any,
) -> None:
    """layer에 prim/property를 생성(또는 재사용)하고 timeSample을 기록."""
    # PrimSpec 확보
    prim_spec = layer.GetPrimAtPath(prim_path)
    if not prim_spec:
        prim_spec = Sdf.CreatePrimInLayer(layer, Sdf.Path(prim_path))

    # AttributeSpec 확보
    attr_spec = prim_spec.attributes.get(prop_name)
    if attr_spec is None:
        sdf_type = _get_sdf_type_for_value(value)
        attr_spec = Sdf.AttributeSpec(prim_spec, prop_name, sdf_type)

    # timeSample 기록 (Sdf.Layer API — 레이어 레벨, thread-safe for anonymous layers)
    attr_path = prim_spec.path.AppendProperty(prop_name)
    layer.SetTimeSample(attr_path, frame, value)


def _parse_value_json(value_json_str: str) -> Any:
    """JSON 문자열 → USD 호환 Python 값 변환.

    _to_simple_value 출력 포맷을 역변환:
      [r, i, j, k] (4요소) → Gf.Quatd
      [x, y, z]   (3요소) → Gf.Vec3d
      float        → float
      str          → str
      None         → None
    """
    try:
        val = json.loads(value_json_str)
    except (json.JSONDecodeError, TypeError):
        return None

    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return float(val)  # USD double 계열에 맞춰 float으로 통일
    if isinstance(val, float):
        return val
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        if len(val) == 4:
            # Quaternion: [real, ix, iy, iz]
            try:
                return Gf.Quatd(
                    float(val[0]),
                    Gf.Vec3d(float(val[1]), float(val[2]), float(val[3])),
                )
            except (TypeError, ValueError):
                pass
        if len(val) == 3:
            try:
                return Gf.Vec3d(float(val[0]), float(val[1]), float(val[2]))
            except (TypeError, ValueError):
                pass
        # 그 외 리스트
        try:
            return [float(v) for v in val]
        except (TypeError, ValueError):
            return str(val)
    return str(val)


def _parse_capture_time(capture_time_str: str) -> float:
    """ISO 8601 문자열 → Unix timestamp (float). 파싱 실패 시 0.0 반환."""
    try:
        dt = datetime.fromisoformat(capture_time_str)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def _compute_frame(capture_time_str: str, t_min: float, fps: float) -> float:
    """capture_time → 프레임 번호 변환."""
    t = _parse_capture_time(capture_time_str)
    return (t - t_min) * fps


def _get_sdf_type_for_value(value: Any) -> Sdf.ValueTypeName:
    """Python/Gf 값에서 Sdf.ValueTypeName 결정."""
    if isinstance(value, Gf.Vec3d):
        return Sdf.ValueTypeNames.Double3
    if isinstance(value, Gf.Quatd):
        return Sdf.ValueTypeNames.Quatd
    if isinstance(value, bool):
        return Sdf.ValueTypeNames.Bool
    if isinstance(value, int):
        return Sdf.ValueTypeNames.Int
    if isinstance(value, float):
        return Sdf.ValueTypeNames.Double
    if isinstance(value, str):
        return Sdf.ValueTypeNames.String
    return Sdf.ValueTypeNames.Token
