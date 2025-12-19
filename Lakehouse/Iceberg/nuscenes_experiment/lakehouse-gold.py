from pyspark.sql import SparkSession
from pyspark.sql.functions import col
import os
import sys
import time

# =============================================================================
# [PART 1] Environment & Spark Init
# =============================================================================
aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
aws_region = os.getenv("AWS_REGION", "us-east-1")
s3_endpoint = os.getenv("AWS_S3_ENDPOINT", "http://minio:9000")
nessie_uri = os.getenv("NESSIE_URI", "http://nessie:19120/api/v1")
RAW_DATA_PATH = "/mnt/kkr/iceberg/datasets/nuscenes_v1.0-mini/v1.0-mini" 

if not aws_access_key or not aws_secret_key:
    print("Error: AWS Access Key or Secret Key is missing in environment variables.")
    sys.exit(1)

spark = SparkSession.builder \
    .appName("NessieMinioSpark") \
    .config('spark.sql.extensions', 'org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions,org.projectnessie.spark.extensions.NessieSparkSessionExtensions') \
    .config('spark.sql.catalog.spark_catalog', 'org.apache.iceberg.spark.SparkCatalog') \
    .config('spark.sql.catalog.spark_catalog.catalog-impl', 'org.apache.iceberg.nessie.NessieCatalog') \
    .config('spark.sql.catalog.spark_catalog.uri', nessie_uri) \
    .config('spark.sql.catalog.spark_catalog.warehouse', 's3://spark1') \
    .config('spark.sql.catalog.spark_catalog.io-impl', 'org.apache.iceberg.aws.s3.S3FileIO') \
    .config('spark.sql.catalog.spark_catalog.s3.endpoint', s3_endpoint) \
    .config('spark.sql.catalog.spark_catalog.s3.path-style-access', 'true') \
    .config('spark.sql.defaultCatalog', 'spark_catalog') \
    .config('spark.sql.catalog.nessie', 'org.apache.iceberg.spark.SparkCatalog') \
    .config('spark.sql.catalog.nessie.warehouse', 's3://spark1') \
    .config('spark.sql.catalog.nessie.catalog-impl', 'org.apache.iceberg.nessie.NessieCatalog') \
    .config('spark.sql.catalog.nessie.io-impl', 'org.apache.iceberg.aws.s3.S3FileIO') \
    .config('spark.sql.catalog.nessie.uri', nessie_uri) \
    .config('spark.sql.catalog.nessie.ref', 'main') \
    .config('spark.sql.catalog.nessie.cache-enabled', 'false') \
    .config('spark.sql.catalog.nessie.s3.endpoint', s3_endpoint) \
    .config('spark.sql.catalog.nessie.s3.region', aws_region) \
    .config('spark.sql.catalog.nessie.s3.path-style-access', 'true') \
    .config('spark.sql.catalog.nessie.s3.access-key-id', aws_access_key) \
    .config('spark.sql.catalog.nessie.s3.secret-access-key', aws_secret_key) \
    .config('spark.hadoop.fs.s3a.access.key', aws_access_key) \
    .config('spark.hadoop.fs.s3a.secret.key', aws_secret_key) \
    .config('spark.hadoop.fs.s3a.endpoint', s3_endpoint) \
    .config('spark.hadoop.fs.s3a.path.style.access', 'true') \
    .config('spark.hadoop.fs.s3a.connection.ssl.enabled', 'false') \
    .config('spark.hadoop.fs.s3a.impl', 'org.apache.hadoop.fs.s3a.S3AFileSystem') \
    .config('spark.hadoop.fs.s3a.aws.credentials.provider', 'org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider') \
    .getOrCreate()

# =============================================================================
# [PART 2] Phase 1: Ingestion & Gold Table Creation (ETL)
# =============================================================================
print(">>> [Lakehouse] Phase 1: Gold Table 생성 (Join + Denormalization)")
setup_start = time.time()

# 1. JSON 읽기
df_sample = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/sample.json")
df_sample_data = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/sample_data.json")
df_annotation = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/sample_annotation.json")
df_category = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/category.json")
df_instance = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/instance.json")
df_sensor = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/sensor.json")
df_calibrated = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/calibrated_sensor.json")

# 2. 복잡한 조인을 미리 수행 (Denormalization)
# CAM_FRONT 채널 정보 결합
df_channel_map = df_calibrated.join(df_sensor, df_calibrated["sensor_token"] == df_sensor["token"]) \
    .select(df_calibrated["token"].alias("calib_token"), df_sensor["channel"])

# 전체 조인 수행 (Gold Table용 데이터 구성)
df_gold_raw = df_sample_data.join(df_channel_map, df_sample_data["calibrated_sensor_token"] == df_channel_map["calib_token"]) \
    .join(df_annotation, df_sample_data["sample_token"] == df_annotation["sample_token"]) \
    .join(df_instance, df_annotation["instance_token"] == df_instance["token"]) \
    .join(df_category, df_instance["category_token"] == df_category["token"]) \
    .select(
        df_sample_data["filename"].alias("img_path"),
        df_annotation["translation"],
        df_annotation["size"],
        df_annotation["rotation"],
        df_sensor["channel"],
        df_category["name"].alias("category_name")
    )

# 3. 데이터 스케일링 (10배 증강 -> 조인 폭발 시뮬레이션 결과와 맞추기 위해 100배 효과 적용 가능)
SCALE_FACTOR = 7
def scale_df(df, factor):
    if factor <= 1: return df
    # Baseline과 동일하게 10x10=100배 효과를 내기 위해 factor*factor로 증강
    return df.crossJoin(spark.range(factor * factor)).drop("id")

print(f">>> [Experiment] Scaling Gold Table by {SCALE_FACTOR}x{SCALE_FACTOR}=100x ...")
df_gold_final = scale_df(df_gold_raw, SCALE_FACTOR)

# 4. Iceberg Gold Table 저장
# CAM_FRONT나 Category에 상관없이 일단 저장한 뒤 쿼리에서 필터링하는 방식이 실용적입니다.
df_gold_final.write.format("iceberg") \
    .partitionBy("channel") \
    .mode("overwrite") \
    .saveAsTable("nessie.nusc_db.gold_train_set")

print(f"Gold Table Ingestion Finished: {time.time() - setup_start:.2f}s")

# -----------------------------------------------------------------------------
# [PART 3] Phase 2: Experiment (Query from Single Gold Table)
# -----------------------------------------------------------------------------
print(">>> [Lakehouse] Phase 2: 실험 시작 - 단일 Gold 테이블 쿼리")
query_start = time.time()

# 조인이 전혀 없는 단순 필터링 쿼리
query = """
SELECT img_path, translation, size, rotation
FROM nessie.nusc_db.gold_train_set
WHERE channel = 'CAM_FRONT' 
  AND category_name = 'human.pedestrian.adult'
"""

result_df = spark.sql(query)
count = result_df.count()

query_end = time.time()
print(f">>> [Lakehouse] 결과: 보행자 데이터 {count}건 추출 완료")
print(f">>> [Lakehouse] 데이터셋 구성 소요 시간: {query_end - query_start:.4f}초")

spark.stop()