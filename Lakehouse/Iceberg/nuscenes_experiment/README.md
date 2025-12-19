# Performance Analysis of Data Lakehouse based on Iceberg OTF

<img width="984" height="584" alt="output" src="https://github.com/user-attachments/assets/08912181-8d2e-4d5d-b9d3-19d3d7c181e5" />

This project investigates the design and performance of a **Data Lakehouse** using **Apache Iceberg**, focusing on the migration from a legacy file-based data lake to a structured Lakehouse architecture.

The experiments utilize the **[nuScenes v1.0-mini](https://www.nuscenes.org/nuscenes)** autonomous driving dataset to compare performance across three stages: Baseline (Legacy), Iceberg-Silver, and Iceberg-Gold.

---

## 📂 Dataset: [nuScenes v1.0-mini](https://www.nuscenes.org/nuscenes) (Partial)

We utilized a subset of the **[nuScenes v1.0-mini](https://www.nuscenes.org/nuscenes)** dataset. The raw data consists of directory-based sensor files (images, pcd) and metadata stored in JSON format.

---

### Source Data Schema (Raw JSON Metadata)

Before migration, the dataset is organized in a relational structure using multiple JSON files. To access specific sensor data, the system must parse and join these files based on token keys.

* **`sample.json`**: Represents a snapshot in time (a scene frame).
* **`sample_data.json`**: Contains metadata for the actual sensor data (images, radar, lidar) linked to a sample.

Below is an actual example of the raw JSON structure used in the Baseline:

```json
/* 1. sample.json - Defines a specific timestamp/frame */
{
  "token": "ca9a282c9e77460f8360f564131a8af5",       // Primary Key (Unique Frame ID)
  "timestamp": 1532402927647951,
  "prev": "",
  "next": "39586f9d59004284a7114a68825e8eec",        // Token for the next frame
  "scene_token": "cc8c0bf57f984915a77078b10eb33198"
}

/* 2. sample_data.json - Links sensor data to a sample */
{
  "token": "5ace90b379af485b9dcb1584b01e7212",
  "sample_token": "39586f9d59004284a7114a68825e8eec", // Foreign Key (Links to sample.json)
  "ego_pose_token": "5ace90b379af485b9dcb1584b01e7212",
  "calibrated_sensor_token": "f4d2a6c281f34a7eb8bb033d82321f79",
  "timestamp": 1532402927814384,
  "fileformat": "pcd",
  "filename": "sweeps/RADAR_FRONT/n015...1532402927814384.pcd", // Actual binary file path
  "is_key_frame": false,
  "height": 0,
  "width": 0
}

```

> **Performance Bottleneck:** In the Baseline approach, retrieving data for a specific time range or channel requires iterative scanning and joining of these JSON files, which causes significant I/O overhead compared to the Iceberg table format.
### Migrated Schema & Target Workload (Iceberg Table)
The raw JSON data is parsed and transformed into the following structured schema. While the schema supports full multi-sensor data, our experiments focused on a specific subset to evaluate query performance.

#### 1. Table Schema
| Column Name | Data Type | Description |
| :--- | :--- | :--- |
| `img_path` | `string` | File path derived from `filename` |
| `translation` | `array<double>` | Object location (x, y, z) |
| `size` | `array<double>` | Object dimensions (w, l, h) |
| `rotation` | `array<double>` | Orientation (Quaternion) |
| `category_name` | `string` | Object classification |
| **`channel`** | **`string`** | **Sensor Channel (Partition Key)** |

> **Note on Partitioning:** The table is partitioned by the **`channel`** column. This structure allows the engine to significantly reduce I/O by skipping unrelated sensor partitions during queries.

#### 2. Experimental Target Data
To accurately measure the performance gap between the Baseline and the Data Lakehouse, we targeted a specific subset of data that requires both **partition pruning** and **column filtering**:

* **Target Channel:** `CAM_FRONT` (Partition Pruning)
* **Target Category:** `human.pedestrian.adult` (Data Filtering)

**Why this choice?**
This workload simulates a real-world autonomous driving scenario (e.g., "Find all pedestrians detected by the front camera") and highlights the efficiency of Iceberg's metadata handling compared to the full-scan approach of the Baseline.

---

## 🏗️ Architecture & Experimental Stages

The research compares three distinct architectural approaches:

### 1. Baseline (File-based Data Lake)
* **Structure:** Raw directory structure containing sensor files and JSON metadata files.
* **Method:** Iterative file listing and parsing of multiple JSON files to link data relationships.

### 2. Iceberg-Silver (Join-on-read)
* **Structure:** Data migrated to Apache Iceberg format.
* **Method:** **Join-on-read**. Data is normalized; queries require joining multiple tables at runtime.

### 3. Iceberg-Gold (Single-table / Pre-aggregated)
* **Structure:** Optimized Iceberg table.
* **Method:** **Single-table** (Denormalized). Data is pre-joined and optimized using techniques like Z-Ordering or Compaction.

---

## 📊 Performance Benchmarks

We measured query latency across different data scales (Scale Factors) to evaluate the scalability of each approach.

### Experiment Conditions
* **Metric:** Query execution time (seconds)
* **Variable:** Scale Factor (N), resulting in $N^2$ data growth.

### Result Table

| Scale Factor (N) | Multiplier ($N^2$) | Approx. Row Count | Baseline (File-based) | Iceberg-Silver (Join-on-read) | Iceberg-Gold (Single-table) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 1x | 27,483 | 0.0620s | 0.2445s | 0.0675s |
| **3** | 9x | 247,347 | 0.4626s | 0.4353s | 0.0993s |
| **5** | 25x | 687,075 | 1.1693s | 0.6587s | 0.1250s |
| **7** | 49x | 1,346,667 | **2.1338s** | **0.9681s** | **0.1497s** |

### Key Findings

1.  **Scalability:**
    * **Baseline:** Performance degrades linearly (or worse) as data volume increases (0.06s → 2.13s). File listing overhead becomes a bottleneck.
    * **Iceberg-Gold:** Shows remarkably stable performance even as data grows by 49x (0.06s → 0.14s).
2.  **Overhead vs. Optimization:**
    * At low data volumes (N=1), **Iceberg-Silver** is slower due to the overhead of the "Join-on-read" operation and Iceberg metadata handling.
    * However, as data scales (N=7), the optimized **Iceberg-Gold** layer outperforms the Baseline by approximately **14x** (2.1338s vs 0.1497s).
