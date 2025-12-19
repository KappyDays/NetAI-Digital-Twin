# Performance Analysis of Data Lakehouse based on Iceberg OTF

This project investigates the design and performance of a **Data Lakehouse** using **Apache Iceberg**, focusing on the migration from a legacy file-based data lake to a structured Lakehouse architecture.

The experiments utilize the **[nuScenes](https://www.nuscenes.org/nuscenes)** autonomous driving dataset to compare performance across three stages: Baseline (Legacy), Iceberg-Silver, and Iceberg-Gold.

---

## 📂 Dataset: [nuScenes](https://www.nuscenes.org/nuscenes) (Partial)

We utilized a subset of the **[nuScenes](https://www.nuscenes.org/nuscenes)** dataset, specifically focusing on sensor data and object annotations.

### Data Schema
The main data table includes sensor paths, object coordinates, dimensions, and categories.

| Column Name | Data Type | Description |
| :--- | :--- | :--- |
| `img_path` | `string` | File path for camera/sensor images |
| `translation` | `array<double>` | Object location (x, y, z) |
| `size` | `array<double>` | Object dimensions (w, l, h) |
| `rotation` | `array<double>` | Orientation (Quaternion) |
| `category_name` | `string` | Object classification (e.g., `movable_object.trafficcone`) |
| **`channel`** | **`string`** | **Sensor Channel (Partition Key)** |

> **Note on Partitioning:** > The table is partitioned by the **`channel`** column (e.g., `RADAR_FRONT_RIGHT`, `LIDAR_TOP`). This explains why `channel` appears in both the column list and partition information in the Hive/Spark schema. Partitioning allows the engine to skip unrelated files during queries, significantly reducing I/O.

---

## 🏗️ Architecture & Experimental Stages

The research compares three distinct architectural approaches:

### 1. Baseline (File-based Data Lake)
* **Structure:** Legacy Parquet files managed by Hive Metastore.
* **Method:** Standard file listing and reading.
* **Characteristics:** Susceptible to the "small files problem" and slower metadata resolution at scale.

### 2. Iceberg-Silver (Join-on-read)
* **Structure:** Data migrated to Apache Iceberg format.
* **Method:** **Join-on-read**. Data is normalized; queries require joining multiple tables at runtime.
* **Characteristics:** Provides ACID transactions and time travel, but join operations incur computational overhead.

### 3. Iceberg-Gold (Single-table / Pre-aggregated)
* **Structure:** Optimized Iceberg table.
* **Method:** **Single-table** (Denormalized). Data is pre-joined and optimized using techniques like Z-Ordering or Compaction.
* **Characteristics:** Minimizes shuffle and seek operations, designed for high-performance analytics.

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