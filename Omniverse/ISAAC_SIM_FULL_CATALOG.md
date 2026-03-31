---
name: Isaac Sim 5.1.0 전체 Extension 카탈로그 (97개 exts + 452 extscache + 72 deprecated)
description: 97개 현행 Extension의 용도, 핵심 클래스, 의존성 + extscache/extsDeprecated 구조 + 카테고리별 API 맵
type: reference
---

# Isaac Sim 5.1.0 전체 Extension 카탈로그

## 디렉토리 요약
- `exts/` — 97개 현행 Extension (`isaacsim.*`)
- `extscache/` — 452개 Kit/Omniverse 플랫폼 Extension (버전 태그 포함, `omni.*`, `carb.*`)
- `extsDeprecated/` — 72개 구버전 (`omni.isaac.*` → `isaacsim.*`로 마이그레이션)
- `extsUser/` — 사용자 Extension 배치 (빈 폴더)

---

## 카테고리별 Extension 맵 (97개 현행)

### App & Setup (3개)
| Extension | 설명 | 핵심 클래스 |
|-----------|------|------------|
| `isaacsim.app.about` | 빌드/버전 정보 표시 | `AboutExtension` |
| `isaacsim.app.selector` | 앱 선택기 (5.1.0에서 deprecated) | `SelectorWindow` |
| `isaacsim.app.setup` | Isaac Sim 앱 초기 설정 | `CreateSetupExtension` |

### Asset Import/Export/Validation (7개)
| Extension | 설명 | 핵심 클래스 |
|-----------|------|------------|
| `isaacsim.asset.browser` | Nucleus 에셋 브라우저 UI | `AssetBrowserExtension`, `AssetBrowserModel` |
| `isaacsim.asset.exporter.urdf` | USD → URDF 변환 | `UrdfExporter` |
| `isaacsim.asset.gen.conveyor` | 컨베이어 벨트 생성 (Command 패턴) | `CreateConveyorBelt` (do/undo) |
| `isaacsim.asset.gen.conveyor.ui` | 컨베이어 벨트 UI | `ConveyorBuilder`, `ConveyorSelector` |
| `isaacsim.asset.gen.omap` | 2D Occupancy Map 생성 | `Extension` |
| `isaacsim.asset.gen.omap.ui` | Occupancy Map UI | `OccupancyMapWindow` |
| `isaacsim.asset.importer.heightmap` | Height Map 가져오기 | `Extension` |
| `isaacsim.asset.importer.mjcf` | MJCF 가져오기 | `MJCFCreateAsset`, `MJCFCreateImportConfig` |
| `isaacsim.asset.importer.urdf` | URDF 가져오기 | `URDFImportRobot`, `URDFParseFile` |
| `isaacsim.asset.validation` | 에셋 유효성 검증 규칙 | `PhysicsJointHasDriveOrMimicAPI` |

### Core API (14개) — Extension 제작의 기반
| Extension | 설명 | 핵심 클래스/함수 |
|-----------|------|-----------------|
| **`isaacsim.core.api`** | **핵심 시뮬레이션 API** | `World`, `Scene`, `BaseController`, `ArticulationController` |
| `isaacsim.core.api` objects | 프리미티브 오브젝트 | `DynamicCuboid`, `FixedCuboid`, `VisualCuboid`, `GroundPlane`, `DynamicCapsule`, `DynamicSphere`, `DynamicCylinder`, `DynamicCone` |
| **`isaacsim.core.prims`** | **USD Prim 래퍼** | `SingleArticulation`, `SingleXFormPrim`, `SingleGeometryPrim`, `SingleRigidPrim`, `RigidPrim`, `GeometryPrim`, `ClothPrim`, `DeformablePrim`, `ParticleSystem` |
| **`isaacsim.core.utils`** | **유틸리티 함수 모음** (42파일) | `add_reference_to_stage`, `define_prim`, `get_prim_at_path`, `set_camera_view`, numpy/torch/warp 변환 |
| `isaacsim.core.cloner` | 효율적 환경 복제 | `Cloner`, `GridCloner` |
| `isaacsim.core.simulation_manager` | 시뮬레이션 상태 관리 | `SimulationManager`, `IsaacEvents` |
| `isaacsim.core.nodes` | OmniGraph 노드 | `BaseResetNode`, `BaseWriterNode` |
| `isaacsim.core.version` | 버전 정보 | `Version` |
| `isaacsim.core.deprecation_manager` | 구버전 호환 | `Extension` |
| `isaacsim.core.throttling` | 프레임 스로틀링 | `Extension` |
| `isaacsim.core.includes` | C++ 헤더 (Python 없음) | — |
| `isaacsim.core.experimental.*` (4개) | **실험적 API** — materials, objects, prims, utils | `GroundPlane`, `CylinderLight`, `Articulation`, `RigidPrim` 등 차세대 API |

### GUI (5개)
| Extension | 설명 | 핵심 클래스 |
|-----------|------|------------|
| **`isaacsim.gui.components`** | **UI 위젯 라이브러리** | `ScrollingWindow`, `CollapsableFrame`, `Button`, `StateButton`, `CheckBox`, `DropDown`, `FloatField`, `IntField`, `StringField`, `TextBlock`, `ColorPicker`, `XYPlot`, `MenuItemDescription` |
| `isaacsim.gui.menu` | Isaac Sim 전용 메뉴 | `CreateMenuExtension`, `EditMenuExtension` |
| `isaacsim.gui.property` | Property Panel 확장 | `ArrayWidgetBuilder` |
| `isaacsim.gui.content_browser` | 콘텐츠 브라우저 | `Extension` |
| `isaacsim.gui.sensors.icon` | 뷰포트 센서 아이콘 | `IconManipulator`, `IconModel` |

### Robot (12개)
| Extension | 설명 | 핵심 클래스 |
|-----------|------|------------|
| **`isaacsim.robot.wheeled_robots`** | **바퀴 로봇** (22파일) | `WheeledRobot`, `DifferentialController`, `HolonomicController`, `AckermannController`, `WheelBasePoseController` |
| `isaacsim.robot.wheeled_robots.ui` | 바퀴 로봇 UI | `DifferentialControllerWindow` |
| **`isaacsim.robot.manipulators`** | **매니퓰레이터** | `PickPlaceController`, `StackingController`, `Gripper`, `ParallelGripper` |
| `isaacsim.robot.manipulators.examples` | Franka 예제 등 | `Franka`, `UR10`, `RMPFlowController` |
| `isaacsim.robot.manipulators.ui` | 매니퓰레이터 UI | `ArticulationPositionWindow` |
| **`isaacsim.robot.policy.examples`** | **RL 정책 예제** | `PolicyController`, `H1FlatTerrainPolicy`, `AnymalFlatTerrainPolicy`, `SpotFlatTerrainPolicy`, `FrankaOpenDrawerPolicy` |
| `isaacsim.robot.surface_gripper` | 흡착/거리 기반 그리퍼 | `CreateSurfaceGripper`, `GripperView` |
| `isaacsim.robot.surface_gripper.ui` | 그리퍼 UI | `SurfaceGripperPropertiesWidget` |
| `isaacsim.robot.schema` | 로봇 USD 스키마 | `RobotLinkNode` |
| `isaacsim.robot_setup.assembler` | 로봇 조립 | `RobotAssembler`, `AssembledRobot` |
| `isaacsim.robot_setup.gain_tuner` | PD Gain 튜닝 | `GainTuner` |
| `isaacsim.robot_setup.wizard` | 로봇 Import 마법사 | `RobotRegistry`, `WheeledRobot`, `Manipulator` |

### Robot Motion (3개)
| Extension | 설명 | 핵심 클래스 |
|-----------|------|------------|
| `isaacsim.robot_motion.motion_generation` | Lula 모션 정책 | `ArticulationMotionPolicy`, `RmpFlow`, `KinematicsSolver` |
| `isaacsim.robot_motion.lula` | Lula Python 인터페이스 | `Extension` |
| `isaacsim.robot_motion.lula_test_widget` | Lula 테스트 UI | `KinematicsController`, `TrajectoryController` |

### Sensors (9개)
| Extension | 설명 | 핵심 클래스 |
|-----------|------|------------|
| **`isaacsim.sensors.camera`** | **카메라 센서 API** | `Camera` (get_rgba, get_depth, set_resolution, lens distortion), `CameraView`, `SingleViewDepthSensor` |
| `isaacsim.sensors.camera.ui` | 카메라 UI | `Extension` |
| `isaacsim.sensors.physics` | **물리 센서** (Contact, IMU, Effort) | `ContactSensor`, `IsaacSensorCreateContactSensor`, `IsaacSensorCreateImuSensor` |
| `isaacsim.sensors.physx` | **PhysX 레이캐스트 센서** (LiDAR, Proximity, Lightbeam) | `RangeSensorCreateLidar`, `IsaacSensorCreateLightBeamSensor` |
| `isaacsim.sensors.rtx` | **RTX 센서** (RTX LiDAR, Radar, Ultrasonic) | `IsaacSensorCreateRtxLidar`, `IsaacSensorCreateRtxRadar` |
| 각 .ui / .examples | UI 컴포넌트 + 사용 예제 | — |

### Storage (1개)
| Extension | 설명 | 핵심 함수 |
|-----------|------|---------|
| **`isaacsim.storage.native`** | **Nucleus 에셋 경로 해석** | `get_assets_root_path()`, `get_nvidia_asset_root_path()`, `check_server()`, `find_nucleus_server()` |

### Replicator / SDG (10개)
| Extension | 설명 |
|-----------|------|
| `isaacsim.replicator.behavior` | 랜덤화/이벤트 스크립트 (SDG) |
| `isaacsim.replicator.domain_randomization` | 도메인 랜덤화 OmniGraph |
| `isaacsim.replicator.examples` | SDG 스니펫/예제 |
| `isaacsim.replicator.grasping` | 그래스핑 SDG 워크플로우 |
| `isaacsim.replicator.mobility_gen` | 모빌리티 데이터 생성 |
| `isaacsim.replicator.writers` | 커스텀 Replicator Writer |
| `isaacsim.replicator.synthetic_recorder` | SDG 레코딩 UI |

### Cortex (AI Behavior) (2개)
| Extension | 설명 | 핵심 클래스 |
|-----------|------|------------|
| `isaacsim.cortex.framework` | 반응형 로봇 행동 프레임워크 | `Commander`, `CortexObject`, `LogicalStateMonitor` |
| `isaacsim.cortex.behaviors` | 샘플 행동 라이브러리 | Pick&Place, Peck 게임, Block Stacking |

### ROS2 (4개)
| Extension | 설명 |
|-----------|------|
| `isaacsim.ros2.bridge` | ROS2 ↔ Isaac Sim 브릿지 (2114파일! 메시지 타입 포함) |
| `isaacsim.ros2.sim_control` | ROS2로 시뮬레이션 제어 |
| `isaacsim.ros2.tf_viewer` | TF 트리 뷰포트 시각화 |
| `isaacsim.ros2.urdf` | ROS2 노드에서 URDF 가져오기 |

### Examples & Templates (4개)
| Extension | 설명 |
|-----------|------|
| **`isaacsim.examples.extension`** | **Extension 템플릿 생성기** (4개 워크플로우) |
| `isaacsim.examples.interactive` | 인터랙티브 샘플 (68파일! BinFilling 등) |
| `isaacsim.examples.browser` | 예제 브라우저 |
| `isaacsim.examples.ui` | UI 위젯 데모 |

### Utilities (5개)
| Extension | 설명 |
|-----------|------|
| `isaacsim.util.camera_inspector` | 카메라 속성 검사 |
| `isaacsim.util.merge_mesh` | 메시 병합 도구 |
| `isaacsim.util.physics` | Collision/Physics 편집 UI |
| `isaacsim.code_editor.jupyter` | Jupyter 통합 |
| `isaacsim.code_editor.vscode` | VS Code 통합 |

### Pip Archives (4개 — Python 패키지 번들)
| Extension | 내용 |
|-----------|------|
| `omni.isaac.core_archive` | numpy, PIL, scipy 등 기본 패키지 |
| `omni.isaac.ml_archive` | **torch**, torchvision 등 ML 패키지 |
| `omni.pip.cloud` | 클라우드 관련 패키지 |
| `omni.pip.compute` | **cv2**, scipy, sklearn 등 컴퓨트 패키지 |

---

## extscache (452개) 주요 카테고리

Kit/Omniverse 플랫폼 기반 Extension (버전 태그 포함):
- `omni.anim.*` — 애니메이션 (AnimGraph, Navigation, Curve 편집)
- `omni.graph.*` — OmniGraph 비주얼 스크립팅
- `omni.kit.*` — Kit UI 프레임워크 (window, menu, viewport, property)
- `omni.physx.*` — PhysX 물리 엔진 바인딩
- `omni.ui.*` / `omni.ui.scene` — UI 렌더링 + 3D Scene 오버레이
- `omni.replicator.*` — Synthetic Data Generation
- `omni.rtx.*` — RTX 렌더링
- `omni.usd.*` — USD 코어 라이브러리
- `isaacsim.replicator.*` / `isaacsim.sensors.*` — Isaac Sim 전용 캐시

### 핵심 extscache (Extension 제작 시 자주 참조)
| Extension | 용도 |
|-----------|------|
| `omni.physx` | PhysX 인터페이스 (`subscribe_physics_step_events`) |
| `omni.timeline` | Timeline 제어 (PLAY/PAUSE/STOP) |
| `omni.ui` | UI 위젯 (Label, Button, Rectangle, Placer 등) |
| `omni.ui.scene` | 3D 뷰포트 오버레이 (SceneView, Manipulator) |
| `omni.kit.viewport.utility` | 뷰포트 유틸리티 |
| `omni.kit.actions.core` | Action Registry (메뉴 등록) |
| `omni.kit.menu.utils` | 메뉴 유틸리티 (add_menu_items/remove_menu_items) |
| `omni.kit.commands` | Command 패턴 (Undo/Redo) |
| `omni.graph.core` | OmniGraph 코어 |
| `omni.anim.navigation.core` | NavMesh 네비게이션 |

---

## extsDeprecated (72개) 네이밍 마이그레이션 맵

| 구버전 (omni.isaac.*) | 현행 (isaacsim.*) |
|----------------------|------------------|
| `omni.isaac.core` | `isaacsim.core.api` + `isaacsim.core.prims` + `isaacsim.core.utils` |
| `omni.isaac.ui` | `isaacsim.gui.components` |
| `omni.isaac.ui_template` | `isaacsim.examples.extension` |
| `omni.isaac.sensor` | `isaacsim.sensors.physics` + `isaacsim.sensors.rtx` + `isaacsim.sensors.camera` |
| `omni.isaac.range_sensor` | `isaacsim.sensors.physx` |
| `omni.isaac.wheeled_robots` | `isaacsim.robot.wheeled_robots` |
| `omni.isaac.manipulators` | `isaacsim.robot.manipulators` |
| `omni.isaac.motion_generation` | `isaacsim.robot_motion.motion_generation` |
| `omni.isaac.nucleus` | `isaacsim.storage.native` |
| `omni.isaac.conveyor` | `isaacsim.asset.gen.conveyor` |
| `omni.isaac.occupancy_map` | `isaacsim.asset.gen.omap` |
| `omni.isaac.cortex` | `isaacsim.cortex.framework` |
| `omni.isaac.examples` | `isaacsim.examples.interactive` |
| `omni.isaac.cloner` | `isaacsim.core.cloner` |
| `omni.isaac.franka` | `isaacsim.robot.manipulators.examples` |
| `omni.isaac.universal_robots` | `isaacsim.robot.manipulators.examples` |
| `omni.isaac.quadruped` | `isaacsim.robot.policy.examples` |
| `omni.isaac.dynamic_control` | 레거시 — `isaacsim.core.prims`로 대체 |
| `omni.isaac.robot_assembler` | `isaacsim.robot_setup.assembler` |
| `omni.isaac.gain_tuner` | `isaacsim.robot_setup.gain_tuner` |
| `omni.isaac.ros2_bridge` | `isaacsim.ros2.bridge` |

---

## Camera 센서 API 상세

```python
from isaacsim.sensors.camera import Camera

cam = Camera(prim_path="/World/Camera", resolution=(640, 480))
cam.initialize()

# 이미지 캡처 (시뮬레이션 PLAY 상태 필수)
rgba = cam.get_rgba()           # shape: (H, W, 4) — 주의: 1D flat 배열 반환 가능 → reshape 필요
depth = cam.get_depth()         # shape: (H, W)
pointcloud = cam.get_pointcloud()

# 해상도
cam.set_resolution((1280, 720))
w, h = cam.get_resolution()

# 좌표계 변환 (camera.py에 정의)
# U_R_TRANSFORM: ROS → USD
# R_U_TRANSFORM: USD → ROS
# W_U_TRANSFORM: USD → World
# U_W_TRANSFORM: World → USD
```

**주의**: `get_rgba()`가 flat 1D 배열을 반환할 수 있음 → `get_resolution()`으로 (H,W) 확인 후 reshape

## H1 휴머노이드 정책 실행 패턴

```python
from isaacsim.robot.policy.examples.robots.h1 import H1FlatTerrainPolicy

h1 = H1FlatTerrainPolicy(prim_path="/World/H1")
h1.initialize()

# 매 physics step에서:
command = np.array([v_x, v_y, w_z])  # 선속도, 횡속도, 각속도
h1.forward(dt=1/60, command=command)
# 내부: observation 69차원 → policy.pt 추론 → ArticulationAction 적용
```

에셋 경로: `/Isaac/Robots/Unitree/H1/h1.usd`
정책 경로: `/Isaac/Samples/Policies/H1_Policies/h1_policy.pt`

## Differential Controller 수학

```
ωR = (2V + ωb) / (2r)    # 오른쪽 바퀴 각속도
ωL = (2V - ωb) / (2r)    # 왼쪽 바퀴 각속도

V = 원하는 선속도, ω = 원하는 각속도, r = 바퀴 반경, b = 바퀴 간 거리
```

```python
from isaacsim.robot.wheeled_robots.controllers import DifferentialController
ctrl = DifferentialController(name="dc", wheel_radius=0.03, wheel_base=0.112)
action = ctrl.forward(command=np.array([linear_vel, angular_vel]))
# → ArticulationAction(joint_velocities=[left_vel, right_vel])
```

## Cuboid 오브젝트 상속 계열

```
SingleXFormPrim → SingleGeometryPrim → VisualCuboid → FixedCuboid → DynamicCuboid
                                                                  (collision=True, rigid_body=True)
                                     → VisualCapsule → FixedCapsule → DynamicCapsule
                                     → VisualSphere → FixedSphere → DynamicSphere
                                     → VisualCylinder → FixedCylinder → DynamicCylinder
                                     → VisualCone → FixedCone → DynamicCone
```

- `Visual*`: 렌더링만 (collision=False, rigid_body=False)
- `Fixed*`: 충돌 있지만 움직이지 않음 (collision=True, rigid_body=False)
- `Dynamic*`: 충돌 + 물리 시뮬레이션 (collision=True, rigid_body=True)

## ConveyorBelt Command 패턴 (동적 Prim 생성 참조)

```python
class CreateConveyorBelt(omni.kit.commands.Command):
    def __init__(self, prim_name, conveyor_prim=None):
        # 모든 인자를 self._인자명으로 저장
        for name, value in vars().items():
            if name != "self":
                setattr(self, f"_{name}", value)

    def do(self):
        # RigidBodyAPI + CollisionAPI + SurfaceVelocityAPI 적용
        UsdPhysics.RigidBodyAPI.Apply(prim)
        UsdPhysics.CollisionAPI.Apply(prim)
        PhysxSchema.PhysxSurfaceVelocityAPI.Apply(prim)
        # OmniGraph Action Graph 프로그래밍 생성
        og.Controller.edit({"graph_path": path}, {
            keys.CREATE_NODES: [...],
            keys.CONNECT: [...]
        })

    def undo(self):
        # prim 제거
```
