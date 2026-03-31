# Omniverse Extensions

## How to Import These Extensions

Navigate to: **Isaac Sim Extensions → Settings → Extension Search Paths**

### Method 1: Direct Import via Git
Import extensions by simply providing a Git URL. Omniverse will automatically clone the repository and register the extension without requiring manual download.

**Prerequisites:** Git must be installed on your system.

**Example: Importing Vehicle-Scenarios Extension**
```
git://github.com/KappyDays/NetAI-Digital-Twin.git?branch=main&dir=Omniverse/omniverse-extensions/Vehicle-Scenarios
```

### Method 2: Local Import
Download the extension repository (folder) and register its local path in the Extension Search Paths.

**Example: Importing Vehicle-Scenarios Extension**
1. Download the `Vehicle-Scenarios` folder
2. Add the local path to Extension Search Paths
   ```
   C:\workspace\NetAI-Digital-Twin\Omniverse\omniverse-extensions\Vehicle-Scenarios
   ```

## Available Extensions

| Extension | Directory | Status | Description |
|-----------|-----------|--------|-------------|
| KKR.TimeTravel | `time.travel/` | **Active (Task 3)** | 백업 시점 기반 Stage/Entity 복원 |
| KKR.Lakehouse | `lakehouse.proto/` | Deprecated | Prim 스캔/USD 내보내기 (Task 1/2/3에서 미사용) |
| dynamic.tracker | `dynamic.tracker/` | Inactive | 실시간 객체 추적 |
| space.heatmap | `space.heatmap/` | Inactive | 공간 혼잡도 히트맵 |
| object.detector | `object.detector/` | Inactive | 객체 감지 오버레이 |
| physics.simulation | `physics.simulation/` | Inactive | 물리 시뮬레이션 |
| stagegraph.viewer | `stagegraph.viewer/` | Inactive | USD Stage 그래프 시각화 |
