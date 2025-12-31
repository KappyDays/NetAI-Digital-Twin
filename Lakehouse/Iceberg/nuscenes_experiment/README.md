# Query Performance & Scalability Analysis: Apache Iceberg Lakehouse

<Figure size 1200x700 with 1 Axes><img width="1184" height="684" alt="image" src="https://github.com/user-attachments/assets/790de880-8ef6-489a-99af-2b7e762e4ae6" />

This project investigates the impact of **data modeling strategies** on query performance and **scalability** within an **Apache Iceberg Data Lakehouse**.

The experiments utilize the **[nuScenes v1.0-mini](https://www.nuscenes.org/nuscenes)** autonomous driving dataset to compare performance across three distinct data processing strategies: **Pure Python (Nested Loop)**, **Spark Iceberg (Standard Join)**, and **Spark Iceberg (Optimized Layout)**.

---

## 📂 1. Dataset Overview

We utilized a subset of the **[nuScenes v1.0](https://www.nuscenes.org/nuscenes)** dataset (nuScenes v1.0-mini). The raw data consists of directory-based sensor files (images, pcd) and highly structured metadata stored in JSON format.

### Source Data Structure (Raw Input)

The legacy system relies on parsing 7 core JSON tables relevant to object detection to reconstruct the dataset metadata. To generate a training dataset, the system must iteratively join these files based on token keys.

* **Core Metadata:** `sample.json`, `sample_data.json`
* **Sensor Metadata:** `sensor.json`, `calibrated_sensor.json`
* **Annotation Metadata:** `sample_annotation.json`, `instance.json`, `category.json`

> **⚠️ Python Loop Bottleneck:** Retrieving specific data (e.g., *"Front Camera only"*) requires scanning unrelated JSON objects and performing heavy in-memory joins using Python loops.

---

## 🏗️ 2. Experimental Strategies

This research compares three architectural approaches to handling this complex metadata, evaluating how data modeling affects scalability.

---

### Phase 1: Pure Python (Nested Loop)

* **Modeling Strategy:** **Unstructured (Schema-on-Read)**.
* The dataset remains as scattered sensor files and **7 distinct JSON metadata files**. No indexing or partitioning is applied.

* **Processing Method:** **Iterative Parsing & Nested Loops**.
* The system loads all JSON files into memory as Python dictionaries.
* Data linkage relies on **nested loops** to manually associate `sample` → `sample_data` → `annotation`.

* **Limitation:** Performance is severely **bottlenecked by CPU overhead** due to Python's iterative processing. Query time increases aggressively as data scale grows.

---

### Phase 2: Spark Iceberg (Standard Join)

* **Modeling Strategy:** **Normalized Tables (Runtime Join)**.
* Data is migrated 1:1 into separate Iceberg tables (e.g., `nessie.nusc_db.samples`, `nessie.nusc_db.annotations`).
* **Optimization:** The `sample_data` table is **partitioned by `channel`**, enabling **Partition Pruning** during sensor data retrieval.

* **Processing Method:** **Distributed Runtime Joins**.
* Queries must execute complex **multi-way joins** at runtime (Compute-on-Read) to link the filtered sensor data with annotations.

* **Limitation:** Despite partition pruning on the sensor table, performance is **bottlenecked by Shuffle Join** overhead. The engine must scan the large, unpartitioned `annotations` table and shuffle data across the cluster to match records.

---

### Phase 3: Spark Iceberg (Optimized Layout)

* **Modeling Strategy:** **Denormalized Table (Pre-joined)**.
* All necessary features (Image paths, 3D Boxes, Categories, Channels) are **pre-computed** into a single table: `nessie.nusc_db.sample_data_gold`.
* **Optimization:** The entire table is physically **partitioned by `channel`**, strictly aligning data storage with the query access pattern.

* **Processing Method:** **Zero-Join & Partition Pruning**.
* The query engine leverages **Partition Pruning** to read *only* the specific data files (e.g., `channel=CAM_FRONT`), skipping all unrelated data.
* No runtime joins are required.

* **Advantage:** **Eliminates Shuffle Joins** entirely and **minimizes I/O**, resulting in consistent sub-second query latency suitable for high-throughput ML data loading.

---

## ❄️ 3. Optimized Schema Design (Denormalized)

The **Optimized Layout** table is designed to support ML data loading workloads efficiently by consolidating all features into a flat schema.

| Column Name | Data Type | Description | Source (Origin) |
| --- | --- | --- | --- |
| `img_path` | `string` | File path derived from `filename` | `sample_data` |
| `translation` | `array<double>` | 3D Global coordinates (x, y, z) | `sample_annotation` |
| `size` | `array<double>` | Object dimensions (w, l, h) | `sample_annotation` |
| `rotation` | `array<double>` | Orientation (Quaternion) | `sample_annotation` |
| `category_name` | `string` | Object classification | `category` |
| **`channel`** | **`string`** | **Sensor Channel (Partition Key)** | `sensor` |

> **Note on Partitioning:** The table is partitioned by the **`channel`** column (e.g., `CAM_FRONT`, `LIDAR_TOP`). This allows the query engine to instantly skip unrelated sensor partitions during file scanning.

---

## 🎯 4. Experimental Workload

We designed a specific query workload to measure the performance gap between the three strategies.

### Target Scenario

The experiment simulates a real-world Autonomous Driving ML data preparation task:

> *"Retrieve image paths and 3D bounding box parameters for **Adult Pedestrians** captured by the **Front Camera**."*

### Query Filters

To evaluate **Partition Pruning** and **Column Projection** capabilities, we applied the following filters:

1. **Sensor Filter:** `channel = 'CAM_FRONT'` (Tests Partition Pruning)
2. **Category Filter:** `category_name = 'human.pedestrian.adult'` (Tests Row Filtering)

### Final Output Data

All three experiments produce the exact same dataset required for training 3D object detection models:

```json
{
  "img_path": "samples/CAM_FRONT/n015-2018...jpg",
  "bbox_translation": [373.21, 1130.48, 1.25],
  "bbox_size": [0.62, 0.67, 1.64],
  "bbox_rotation": [0.98, 0.00, 0.00, -0.18]
}

```

---

## 📊 5. Performance Benchmarks

We measured query execution time across different data scales to evaluate scalability. The **Data Scale Multiple ()** represents the complexity growth as both `sample_data` and `annotations` increase.

### Result Table

| Data Scale Factor | Pure Python (Nested Loop) | Spark Iceberg (Normalized) | Spark Iceberg (Denormalized) |
| --- | --- | --- | --- |
| **1** | 0.0273s | 0.1613s | 0.0527s |
| **9** | 0.2350s | 0.2279s | 0.0551s |
| **25** | 0.6232s | 0.3634s | 0.0740s |
| **49** | **1.1253s** | **0.5480s** | **0.0799s** |

### Key Findings

1. **Inefficiency of Pure Python:**
* The **Pure Python (Nested Loop)** approach shows rapid linear degradation. The overhead of iterative dictionary lookups and sequential processing becomes the dominant bottleneck as  increases.


2. **Cost of Standard Joins:**
* The **Spark Iceberg (Standard Join)** strategy performs better than Python at scale but is still limited by distributed computing physics.
* Even with Iceberg, the **Runtime Join costs** (Shuffling) between the partitioned sensor table and unpartitioned annotation table prevent linear scalability.


3. **Superiority of Optimized Layout:**
* The **Spark Iceberg (Optimized Layout)** demonstrates superior scalability, maintaining sub-second latency (**~0.08s**) even at 49x scale ().
* By leveraging **Partition Pruning** (skipping files) and **Pre-computation** (eliminating joins), it outperforms the Baseline by approximately **14x** at scale.



```

```
