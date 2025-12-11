import os
import requests
from pyspark.sql import SparkSession
from delta import configure_spark_with_delta_pip
import logging

from dotenv import load_dotenv
load_dotenv(dotenv_path='.my_env')

class SparkBuilder():
    def __init__(self, save_path='jars'):

        # 로깅 설정
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)        
        
        # 필요한 JAR 파일 다운로드
        jars_info = self._download_jar(save_path=save_path)
            
        # JAR 파일 경로 설정
        jars = ','.join([os.path.abspath(os.path.join(save_path, jar)) for jar in jars_info.keys()])
        print(jars)

        # SparkSession 생성
        builder = SparkSession.builder \
            .appName("DeltaLakeExample") \
            .config("spark.jars", jars) \
            .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
            .config("spark.hadoop.fs.s3a.endpoint", f"http://{os.getenv('LOCAL_IP_ADDRESS')}:9040") \
            .config("spark.hadoop.fs.s3a.access.key", "pRWLQmzIoCE5nUKyac1O") \
            .config("spark.hadoop.fs.s3a.secret.key", "8FpYdGdHL14opVBipvvGzjScTMNaQSHOjH9WaUZp") \
            .config("spark.hadoop.fs.s3a.path.style.access", "true") \
            .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false") \
            .config("spark.hadoop.fs.s3a.aws.credentials.provider", 
                    "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider") \
            .config("spark.driver.extraClassPath", f"{save_path}/postgresql-42.7.4.jar")

        # Delta Lake 설정 추가
        builder = builder \
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
            
        self.spark = configure_spark_with_delta_pip(builder).getOrCreate()
        
    # JAR 파일 다운로드 함수
    def _download_jar(self, save_path):
        # 다운로드 목록
        jars_info = {
            "hadoop-aws-3.3.1.jar": "https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.3.1/hadoop-aws-3.3.1.jar",
            "aws-java-sdk-bundle-1.11.901.jar": "https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/1.11.901/aws-java-sdk-bundle-1.11.901.jar",
            "hadoop-common-3.3.1.jar": "https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-common/3.3.1/hadoop-common-3.3.1.jar",
            "postgresql-42.7.4.jar": "https://jdbc.postgresql.org/download/postgresql-42.7.4.jar"
        }
        
        # for filename, url in jars_info.items():        
        #     pass
        #     filename = os.path.join(save_path, filename)
        #     if not os.path.exists(filename):
        #         self.logger.info(f"Downloading {filename}...")
        #         response = requests.get(url, stream=True)
        #         response.raise_for_status()  # 다운로드 오류 발생 시 예외 처리
        #         with open(filename, 'wb') as f:
        #             for chunk in response.iter_content(chunk_size=8192):
        #                 if chunk:  # chunk가 비어있지 않을 경우에만 기록
        #                     f.write(chunk)
        #         self.logger.info(f"Downloaded {filename}")
        #     else:
        #         self.logger.info(f"{filename} already exists. Skipping download.")
        
        return jars_info