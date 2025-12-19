from pyspark.sql import SparkSession
from pyspark.sql.functions import col
import os
import sys
import time

# =============================================================================
# [PART 1] Environment & Spark Init (사용자 설정 유지)
# =============================================================================
aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
aws_region = os.getenv("AWS_REGION", "us-east-1")
s3_endpoint = os.getenv("AWS_S3_ENDPOINT", "http://minio:9000")
nessie_uri = os.getenv("NESSIE_URI", "http://nessie:19120/api/v1")

# 데이터 경로 확인
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
# [PART 2] 로직 부분 (save -> saveAsTable 수정됨)
# =============================================================================

# -----------------------------------------------------------------------------
# 2. Phase 1: Ingestion (ETL)
# -----------------------------------------------------------------------------
print(">>> [Lakehouse] Phase 1: 데이터 적재 (ETL & Denormalization)")
setup_start = time.time()

# Namespace 생성
spark.sql("CREATE NAMESPACE IF NOT EXISTS nessie.nusc_db")

try:
    # 테이블이 이미 있는지 확인 (테스트용)
    # spark.table("nessie.nusc_db.sample_data") # 이 부분은 주석 처리하거나 에러 핸들링을 위해 둠
    # print("Tables might exist. Attempting to overwrite...")
    pass
except:
    pass

# 1. JSON 읽기
df_sample = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/sample.json")
df_sample_data = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/sample_data.json")
df_annotation = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/sample_annotation.json")
df_category = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/category.json")
df_instance = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/instance.json")
df_sensor = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/sensor.json")
df_calibrated = spark.read.option("multiLine", True).json(f"{RAW_DATA_PATH}/calibrated_sensor.json")

# 2. Pre-Join (Denormalization)
df_channel_map = df_calibrated.join(
    df_sensor, 
    df_calibrated["sensor_token"] == df_sensor["token"]
).select(
    df_calibrated["token"].alias("calib_token"), 
    df_sensor["channel"]
)

df_sample_data_enriched = df_sample_data.join(
    df_channel_map,
    df_sample_data["calibrated_sensor_token"] == df_channel_map["calib_token"]
).drop("calib_token")

# =========================================================
# [실험 변수] 데이터 스케일 팩터
# =========================================================
SCALE_FACTOR = 10 

def scale_df(df, factor):
    if factor <= 1: return df
    return df.crossJoin(spark.range(factor)).drop("id")

print(f">>> [Experiment] Scaling Key Tables by {SCALE_FACTOR}x (others keep 1x) ...")

# 1. 참조 테이블 (Reference Tables) - 스케일링 하지 않음 (Python Dictionary 동작 모사)
# samples, instances, category는 1배 유지
df_sample.write.format("iceberg").mode("overwrite").saveAsTable("nessie.nusc_db.samples")
df_category.write.format("iceberg").mode("overwrite").saveAsTable("nessie.nusc_db.category")
df_instance.write.format("iceberg").mode("overwrite").saveAsTable("nessie.nusc_db.instances")

# 2. 팩트 테이블 (Fact Tables) - 스케일링 적용 (데이터 폭증 유발)
# sample_data와 annotations만 늘려서 10 * 10 = 100배 효과를 냄
scale_df(df_sample_data_enriched, SCALE_FACTOR).write.format("iceberg") \
    .partitionBy("channel") \
    .mode("overwrite") \
    .saveAsTable("nessie.nusc_db.sample_data")

scale_df(df_annotation, SCALE_FACTOR).write.format("iceberg").mode("overwrite").saveAsTable("nessie.nusc_db.annotations")

print(f"Data Ingestion Finished: {time.time() - setup_start:.2f}s")

# # 3. Iceberg 저장 [수정된 부분: save -> saveAsTable]
# # saveAsTable은 테이블이 없으면 생성(Create), 있으면 덮어쓰기(Overwrite)를 수행합니다.
# df_sample.write.format("iceberg").mode("overwrite").saveAsTable("nessie.nusc_db.samples")

# df_sample_data_enriched.write.format("iceberg") \
#     .partitionBy("channel") \
#     .mode("overwrite") \
#     .saveAsTable("nessie.nusc_db.sample_data")
    
# df_annotation.write.format("iceberg").mode("overwrite").saveAsTable("nessie.nusc_db.annotations")
# df_category.write.format("iceberg").mode("overwrite").saveAsTable("nessie.nusc_db.category")
# df_instance.write.format("iceberg").mode("overwrite").saveAsTable("nessie.nusc_db.instances")

# print(f"Data Ingestion Finished: {time.time() - setup_start:.2f}s")

# -----------------------------------------------------------------------------
# 3. Phase 2: Experiment (Query)
# -----------------------------------------------------------------------------
print(">>> [Lakehouse] Phase 2: 실험 시작 - 모델 학습 데이터셋 구성 쿼리")
query_start = time.time()

query = """
SELECT 
    sd.filename as img_path,
    a.translation,
    a.size,
    a.rotation
FROM nessie.nusc_db.samples s
JOIN nessie.nusc_db.sample_data sd 
    ON s.token = sd.sample_token
JOIN nessie.nusc_db.annotations a 
    ON s.token = a.sample_token
JOIN nessie.nusc_db.instances i 
    ON a.instance_token = i.token
JOIN nessie.nusc_db.category c 
    ON i.category_token = c.token
WHERE 
    sd.channel = 'CAM_FRONT' 
    AND c.name = 'human.pedestrian.adult'
"""

result_df = spark.sql(query)
count = result_df.count()

query_end = time.time()
print(f">>> [Lakehouse] 결과: 보행자 데이터 {count}건 추출 완료")
print(f">>> [Lakehouse] 데이터셋 구성 소요 시간: {query_end - query_start:.4f}초")

spark.stop()