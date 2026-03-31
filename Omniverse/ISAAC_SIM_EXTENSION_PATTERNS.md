---
name: Isaac Sim 5.1.0 Extension 제작 종합 레퍼런스
description: NVIDIA Isaac Sim 5.1.0의 Extension 제작 패턴, 4개 워크플로우 템플릿, GUI 컴포넌트, 핵심 API, Nucleus 에셋, 네이밍 마이그레이션, 주의사항 종합 정리
type: reference
---

# Isaac Sim 5.1.0 Extension 제작 종합 레퍼런스

설치 경로: `C:\workspace\isaac-sim-standalone-5.1.0-windows-x86_64`

---

## 1. Extension 디렉토리 구조

| 디렉토리 | 개수 | 용도 |
|----------|------|------|
| `exts/` | 97개 | **현행 Isaac Sim 공식 Extension** (`isaacsim.*` 네임스페이스) |
| `extscache/` | 452개 | **Kit/Omniverse 플랫폼 Extension** (`omni.*`, `carb.*` 등), 버전 태그 포함 |
| `extsDeprecated/` | 72개 | **구버전 Extension** (`omni.isaac.*` → `isaacsim.*`로 마이그레이션됨) |
| `extsUser/` | 0개 | **사용자 Extension 배치 경로** (여기에 커스텀 Extension 폴더를 넣으면 자동 감지) |

### 네이밍 마이그레이션 (5.1.0)
- `omni.isaac.core` → `isaacsim.core.api` + `isaacsim.core.prims` + `isaacsim.core.utils`
- `omni.isaac.ui` → `isaacsim.gui.components`
- `omni.isaac.ui_template` → `isaacsim.examples.extension`
- `omni.isaac.wheeled_robots` → `isaacsim.robot.wheeled_robots`
- `omni.isaac.nucleus` → `isaacsim.storage.native`
- `omni.isaac.sensor` → `isaacsim.sensors.physics` / `isaacsim.sensors.rtx` / `isaacsim.sensors.camera`
- `omni.isaac.motion_generation` → `isaacsim.robot_motion.motion_generation`
- **주의**: 인터넷 예제의 `omni.isaac.*` import는 5.1.0에서 동작하지 않음. `isaacsim.*`으로 변환 필요

---

## 2. Extension 파일 구조 (공식 템플릿)

```
my.extension/
├── config/
│   └── extension.toml           # 메타데이터, 의존성, 모듈명
├── data/
│   ├── icon.png                 # 32x32 아이콘
│   └── preview.png              # 미리보기 이미지
├── docs/
│   ├── README.md
│   └── CHANGELOG.md
├── My_Extension_python/         # [[python.module]] name과 일치해야 함
│   ├── __init__.py              # 반드시 `from .extension import *` 포함
│   ├── global_variables.py      # EXTENSION_TITLE, EXTENSION_DESCRIPTION
│   ├── extension.py             # omni.ext.IExt 보일러플레이트 (수정하지 않음)
│   ├── ui_builder.py            # 사용자 진입점 — UI 구성 + 콜백 로직
│   └── scenario.py              # (선택) 시나리오 로직 분리
```

### extension.toml 템플릿 (모든 필드 필수)
```toml
[package]
version = "1.0.0"
category = "Simulation"
title = "My.Extension"
description = "..."
authors = ["KKR"]
repository = ""
keywords = ["keyword1", "keyword2"]
changelog = "docs/CHANGELOG.md"
readme = "docs/README.md"
preview_image = "data/preview.png"
icon = "data/icon.png"
writeTarget.kit = true

[dependencies]
"isaacsim.core.api" = {}
"isaacsim.gui.components" = {}
"omni.kit.uiapp" = {}

[[python.module]]
name = "My_Extension_python"
```

### __init__.py (필수!)
```python
from .extension import *
```
**주의**: 이 줄이 없으면 Kit이 Extension 클래스를 발견하지 못해 로딩 실패

---

## 3. 4개 워크플로우 템플릿

소스 위치: `exts/isaacsim.examples.extension/template_source_files/`

### 3a. Configuration Tooling Workflow
- **용도**: 로봇 관절 제어, 파라미터 조정 등 설정 도구
- **파일**: extension.py + global_variables.py + ui_builder.py
- **특징**: DropDown으로 Articulation 선택 → 물리 실행 중 관절 제어
- **핵심 패턴**: `SingleArticulation` 초기화 → `ArticulationAction` 적용
- **이 프로젝트의 KKR Extension들이 사용하는 패턴**

### 3b. Loaded Scenario Workflow
- **용도**: Load → Reset → Run 패턴의 시나리오 실행
- **파일**: extension.py + global_variables.py + ui_builder.py + scenario.py
- **특징**: `core.World()`와 통합, 시나리오 클래스에 setup/teardown/update 분리
- **핵심 패턴**: `ScenarioTemplate` 상속 → `setup_scenario()` / `update_scenario(step)`

### 3c. Scripting Workflow
- **용도**: 여러 프레임에 걸친 장시간 스크립트 실행 (로봇 피킹 등)
- **파일**: extension.py + global_variables.py + ui_builder.py + scenario.py
- **특징**: **Python Generator/yield 패턴**으로 프레임별 실행
- **핵심 패턴**:
  ```python
  def update(self, step):
      try: next(self._script_generator)
      except StopIteration: return True

  def my_script(self):
      yield from self.goto_position(target)  # 여러 프레임 대기
      yield from self.open_gripper()
  ```

### 3d. UI Component Library
- **용도**: 사용 가능한 모든 UI 위젯 데모
- **파일**: extension.py + global_variables.py + ui_builder.py
- **특징**: GUI wrapper 컴포넌트 전체 사용 예제

---

## 4. extension.py 보일러플레이트 (수정하지 않는 파일)

```python
class Extension(omni.ext.IExt):
    def on_startup(self, ext_id):
        # 1. ScrollingWindow 생성 (visible=False)
        # 2. Action Registry에 메뉴 액션 등록
        # 3. MenuItemDescription으로 메뉴 항목 추가
        # 4. UIBuilder 인스턴스 생성
        # 5. PhysX 인터페이스, Timeline 인터페이스 획득
        # 6. 이벤트 구독 변수 초기화 (None)

    def on_shutdown(self):
        # 1. 메뉴 항목 제거
        # 2. Action 등록 해제
        # 3. Window = None
        # 4. ui_builder.cleanup()
        # 5. gc.collect()

    def _on_window(self, visible):
        if visible:
            # Stage event + Timeline event 구독
            self._build_ui()
        else:
            # 구독 해제 (= None)
            self.ui_builder.cleanup()

    def _on_timeline_event(self, event):
        if PLAY: subscribe_physics_step_events
        elif STOP: physx_subscription = None

    def _on_physics_step(self, step):
        self.ui_builder.on_physics_step(step)

    def _on_stage_event(self, event):
        if OPENED or CLOSED: physx_sub = None; cleanup()
```

### 수명주기 흐름
```
on_startup → _on_window(visible) → _build_ui → build_ui()
                                             → on_menu_callback()
PLAY → subscribe_physics → on_physics_step(step) [60Hz]
STOP → unsubscribe physics
Stage OPENED/CLOSED → cleanup()
on_shutdown → cleanup → gc.collect
```

### KKR-Tools 메뉴 등록 패턴 (이 프로젝트 전용)
```python
# Tools > KKR-Tools 서브메뉴 + 체크마크 토글
action_registry.register_action(ext_id, f"ToggleWindow:{TITLE}", callback)
self._menu_items = [MenuItemDescription(
    name=TITLE, ticked=True,
    ticked_fn=lambda: self._window.visible if self._window else False,
    onclick_action=(ext_id, f"ToggleWindow:{TITLE}"),
)]
self._menu_items = [MenuItemDescription(name="KKR-Tools", sub_menu=self._menu_items)]
add_menu_items(self._menu_items, "Tools")
```

---

## 5. UIBuilder 계약 (사용자가 구현하는 파일)

```python
class UIBuilder:
    def __init__(self):
        self.frames = []              # CollapsableFrame 목록
        self.wrapped_ui_elements = [] # cleanup 대상 UI 위젯 목록

    # === 자동 호출 (extension.py가 호출) ===
    def build_ui(self): ...           # UI 구성 (매번 윈도우 열릴 때)
    def on_menu_callback(self): ...   # 메뉴 클릭 후 호출
    def on_timeline_event(self, event): ...  # PLAY/PAUSE/STOP
    def on_physics_step(self, step): ...     # 물리 스텝 (60Hz)
    def on_stage_event(self, event): ...     # Stage 열기/닫기
    def cleanup(self): ...            # 리소스 정리
```

### cleanup() 구현 패턴
```python
def cleanup(self):
    for ui_elem in self.wrapped_ui_elements:
        ui_elem.cleanup()
```

---

## 6. GUI 컴포넌트 라이브러리

소스: `isaacsim.gui.components.element_wrappers`

| 위젯 | 용도 | 주요 매개변수 |
|-------|------|-------------|
| `CollapsableFrame` | 접이식 섹션 | title, collapsed |
| `ScrollingFrame` | 스크롤 가능 프레임 | title |
| `Button` | 클릭 버튼 | label, text, on_click_fn |
| `StateButton` | A/B 상태 토글 | a_text, b_text, on_a_click_fn, on_b_click_fn |
| `CheckBox` | 체크박스 | label, default_value, on_click_fn |
| `IntField` | 정수 입력 | label, default_value, lower_limit, upper_limit |
| `FloatField` | 실수 입력 | label, default_value, step, format, lower/upper_limit |
| `StringField` | 문자열 입력 | label, read_only, use_folder_picker |
| `DropDown` | 드롭다운 선택 | label, populate_fn, on_selection_fn |
| `TextBlock` | 읽기전용 텍스트 | label, num_lines, include_copy_button |
| `ColorPicker` | 색상 선택 | label, default_value |
| `XYPlot` | 2D 그래프 | x_data, y_data, legends, plot_colors |

### DropDown 특수 기능
```python
# Stage에서 특정 타입의 USD 오브젝트 자동 검색
dropdown.set_populate_fn_to_find_all_usd_objects_of_type("articulation")
dropdown.repopulate()  # 수동 호출 필요
dropdown.trigger_on_selection_fn_with_current_selection()  # 현재 선택 재트리거
```

### 스타일 적용
```python
from isaacsim.gui.components.ui_utils import get_style
with ui.VStack(style=get_style(), spacing=5, height=0):
    ...
```

---

## 7. 핵심 API 모듈

### isaacsim.core.api
```python
from isaacsim.core.api import World
world = World(physics_dt=1/60, stage_units_in_meters=0.01)
# 기본: gravity=-9.81, TGS solver, /physicsScene 경로
```

### isaacsim.core.api.objects (프리미티브 오브젝트)
```python
from isaacsim.core.api.objects import DynamicCuboid, FixedCuboid, VisualCuboid, GroundPlane
ground = GroundPlane(prim_path="/World/Ground", z_position=0)
cube = DynamicCuboid(prim_path="/World/cube", position=np.array([0,0,0.5]), size=0.3, color=np.array([1,0,0]))
```

### isaacsim.core.prims (USD Prim 래퍼)
```python
from isaacsim.core.prims import SingleArticulation, SingleXFormPrim, RigidPrim, GeometryPrim
robot = SingleArticulation("/World/robot")
robot.initialize()
robot.apply_action(ArticulationAction(joint_positions=np.array([...]), joint_indices=np.array([...])))
prim = GeometryPrim("/World/obj")
prim.apply_collision_apis()
```

### isaacsim.core.utils.stage (Stage 유틸리티)
```python
from isaacsim.core.utils.stage import add_reference_to_stage, get_current_stage, clear_stage, set_stage_up_axis
add_reference_to_stage(usd_path, prim_path)  # Nucleus/로컬 USD 로딩
```

### isaacsim.core.utils.types
```python
from isaacsim.core.utils.types import ArticulationAction
action = ArticulationAction(joint_positions=..., joint_velocities=..., joint_indices=...)
```

### isaacsim.storage.native (Nucleus 에셋)
```python
from isaacsim.storage.native import get_assets_root_path
root = get_assets_root_path()  # None if Nucleus unavailable
usd = root + "/Isaac/Robots/NVIDIA/Jetbot/jetbot.usd"
```

### Physics API (pxr)
```python
from pxr import UsdGeom, UsdPhysics, UsdLux, Gf, Sdf, PhysxSchema
UsdPhysics.RigidBodyAPI.Apply(prim)
UsdPhysics.CollisionAPI.Apply(prim)
rigid = UsdPhysics.RigidBodyAPI.Apply(prim)
rigid.CreateKinematicEnabledAttr(True)  # 키네마틱 바디
UsdPhysics.Scene.Define(stage, "/physicsScene")
```

---

## 8. Nucleus 에셋 카탈로그

### 로봇
| 이름 | 경로 |
|------|------|
| Jetbot | `/Isaac/Robots/NVIDIA/Jetbot/jetbot.usd` |
| Nova Carter | `/Isaac/Robots/NVIDIA/NovaCarter/nova_carter.usd` |
| Carter v1 | `/Isaac/Robots/NVIDIA/Carter/carter_v1_physx_lidar.usd` |
| Kaya | `/Isaac/Robots/NVIDIA/Kaya/kaya.usd` |
| Franka Panda | `/Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd` |
| UR10 | `/Isaac/Robots/UniversalRobots/ur10/ur10.usd` |
| Ant (4족) | `/Isaac/Robots/IsaacSim/Ant/ant.usd` |
| H1 (휴머노이드) | `/Isaac/Robots/Unitree/H1/h1.usd` |

### 환경
| 이름 | 경로 |
|------|------|
| Warehouse (Full) | `/Isaac/Environments/Simple_Warehouse/full_warehouse.usd` |
| Warehouse (Base) | `/Isaac/Environments/Simple_Warehouse/warehouse.usd` |
| Grid Default | `/Isaac/Environments/Grid/default_environment.usd` |
| Grid Black Room | `/Isaac/Environments/Grid/gridroom_black.usd` |

### Props
| 이름 | 경로 |
|------|------|
| Frame Prim (UI) | `/Isaac/Props/UIElements/frame_prim.usd` |
| Dolly | `/Isaac/Props/Dolly/dolly.usd` |
| Forklift | `/Isaac/Props/Forklift/forklift.usd` |
| YCB Objects (Physics) | `/Isaac/Props/YCB/Axis_Aligned_Physics/` |

---

## 9. 주요 패턴 & 베스트 프랙티스

### 에셋 로딩 + Fallback
```python
def _try_load_asset(stage, asset_suffix, prim_path):
    try:
        root = get_assets_root_path()
        if root is None: return False
        add_reference_to_stage(root + asset_suffix, prim_path)
        return stage.GetPrimAtPath(prim_path).IsValid()
    except Exception:
        return False
# Fallback: UsdGeom.Cube/Capsule로 프리미티브 생성
```

### 비동기 작업 (네트워크 I/O 등)
```python
async def _async_task():
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, blocking_fn)
    # UI 업데이트
asyncio.ensure_future(_async_task())
```

### 윈도우 도킹
```python
async def dock_window():
    await omni.kit.app.get_app().next_update_async()
    tgt = ui.Workspace.get_window("Viewport")
    window = omni.ui.Workspace.get_window(TITLE)
    if window and tgt:
        window.dock_in(tgt, omni.ui.DockPosition.LEFT, 0.33)
asyncio.ensure_future(dock_window())
```

### Command 패턴 (Undo/Redo 지원)
```python
class CreateSomething(omni.kit.commands.Command):
    def __init__(self, **kwargs): ...
    def do(self): ... # 생성
    def undo(self): ... # 제거
omni.kit.commands.register_all_commands_in_module(__name__)
_, result = omni.kit.commands.execute("CreateSomething", param=value)
```

### Material 생성/바인딩
```python
from pxr import UsdShade
omni.kit.commands.execute("CreateMdlMaterialPrim", mtl_url=path, mtl_name="name", mtl_path=path)
UsdShade.MaterialBindingAPI(prim).Bind(material, UsdShade.Tokens.strongerThanDescendants)
```

---

## 10. 로봇 제어 패턴

### Wheeled Robot (Differential Drive)
```python
from isaacsim.robot.wheeled_robots import WheeledRobot
from isaacsim.robot.wheeled_robots.controllers import DifferentialController
robot = WheeledRobot(prim_path="/path", wheel_dof_names=["left", "right"])
robot.initialize()
controller = DifferentialController(name="ctrl", wheel_radius=0.03, wheel_base=0.112)
action = controller.forward(command=[linear_vel, angular_vel])
robot.apply_action(action)
```

### Articulation Control (일반)
```python
robot = SingleArticulation("/World/robot")
robot.initialize()
robot._articulation_controller.switch_control_mode(mode="velocity")
action = ArticulationAction(joint_velocities=np.array([v1, v2]), joint_indices=np.array([0, 1]))
robot.apply_action(action)
```

---

## 11. 흔한 실수 & 디버깅

| 증상 | 원인 | 해결 |
|------|------|------|
| Extension이 메뉴에 안 나타남 | `__init__.py`가 비어있음 | `from .extension import *` 추가 |
| `NameError: 'omni' is not defined` | import 누락 | `import omni`, `import omni.kit.app` 추가 |
| Camera `get_rgba()` 에러 | 1D flat 배열 반환 | `get_resolution()`으로 reshape 필요 |
| Physics step이 호출 안 됨 | Timeline이 PLAY 상태가 아님 | Play 버튼 필요. 구독은 PLAY 이벤트에서 |
| Articulation initialize 실패 | Timeline STOP 상태에서 호출 | PLAY 후 초기화해야 함 |
| `ui.Placer` 위치가 (0,0) | `with` 없이 사용 | 반드시 `with ui.Placer():` context manager |
| Stage 닫을 때 KeyError | Kit 내부 캐시 문제 | 무시해도 됨 (알려진 이슈) |
| Extension 비활성화 시 cleanup 누락 | wrapped_ui_elements cleanup 미호출 | `cleanup()`에서 모든 위젯 순회 |
| 에셋 로딩 실패 | Nucleus 미연결 | `get_assets_root_path()`가 None 반환 → fallback |

---

## 12. 의존성 가용 패키지

Extension 내에서 사용 가능한 패키지 (Isaac Sim Python 런타임에 번들):
- **항상 가능**: `numpy`, `PIL`, `cv2`, `torch` (GPU), `carb`, `omni.*`, `pxr.*`
- **항상 가능**: `urllib`, `json`, `asyncio`, `dataclasses` (stdlib)
- **사용 불가**: `pip install`로 설치한 외부 패키지 (requests, flask 등)
- **예외**: `ultralytics` (YOLOv8)는 Isaac Sim 5.1.0에 번들됨

### 로깅
```python
import carb
carb.log_info("Info message")
carb.log_warn("Warning message")
carb.log_error("Error message")
```

---

## 13. Extension 로딩 방법

```bash
# 방법 1: 커맨드라인 플래그
isaac-sim.bat --ext-folder /path/to/exts --enable my.extension

# 방법 2: Extension Manager UI
# Third Party Extensions에서 경로 추가 후 검색

# 방법 3: extsUser/ 폴더에 배치
# 자동 감지됨

# 방법 4: app 파일에 직접 추가
# apps/*.kit 파일에 [dependencies] 추가
```

---

## 14. 이 프로젝트(KKR) Extension 규칙

- **모든 Extension은 Tools > KKR-Tools 서브메뉴에 등록** (체크마크 토글)
- **Configuration Tooling Workflow** 템플릿 사용 (extension.py 수정 금지)
- **의존성**: `isaacsim.core.api` + `isaacsim.gui.components` + `omni.kit.uiapp`
- **모든 Custom 로직은 ui_builder.py와 추가 모듈에 작성**
- `extension.py`는 lakehouse.proto에서 복사 (verbatim)
- `__init__.py`에 `from .extension import *` 필수
