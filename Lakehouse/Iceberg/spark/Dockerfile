# =============================================================================
# Apache Spark + Iceberg — Custom Docker Image
# =============================================================================
# Extends bitnami/spark with pre-installed Apache Iceberg runtime JARs,
# AWS S3 (MinIO) connectivity, and Polaris REST catalog integration.
#
# Purpose:
#   - Batch processing of Static/Dynamic Prim data
#   - Schema evolution operations on Iceberg tables
#   - Data compaction and maintenance (expire snapshots, rewrite manifests)
#
# Compatible with both Spark master and worker modes via SPARK_MODE env var.
#
# Build context: Lakehouse/Iceberg/spark/
# =============================================================================

FROM bitnami/spark:3.5

# OCI labels for registry and research documentation
LABEL org.opencontainers.image.title="NetAI-Digital-Twin Spark Iceberg Worker" \
      org.opencontainers.image.description="Apache Spark 3.5 with Iceberg 1.7.1 runtime for Lakehouse batch processing" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.authors="NetAI Lab" \
      org.opencontainers.image.licenses="MIT"

# ---------------------------------------------------------------------------
# Version pins — centralised for reproducible builds
# ---------------------------------------------------------------------------
ENV ICEBERG_VERSION=1.7.1 \
    AWS_SDK_VERSION=2.28.19

# ---------------------------------------------------------------------------
# Download Iceberg + AWS S3 JARs into Spark's classpath
# ---------------------------------------------------------------------------
# These JARs are required at runtime for:
#   1. iceberg-spark-runtime  — Iceberg table format support in Spark SQL
#   2. aws-bundle             — S3FileIO for MinIO object storage access
#   3. url-connection-client  — HTTP transport for Polaris REST catalog
#
# All JARs are fetched from Maven Central and placed in the Spark jars
# directory so they are automatically loaded by both master and worker nodes.
USER root

RUN curl -fSL -o /opt/bitnami/spark/jars/iceberg-spark-runtime-3.5_2.12-${ICEBERG_VERSION}.jar \
        "https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/${ICEBERG_VERSION}/iceberg-spark-runtime-3.5_2.12-${ICEBERG_VERSION}.jar" && \
    curl -fSL -o /opt/bitnami/spark/jars/iceberg-aws-bundle-${ICEBERG_VERSION}.jar \
        "https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-aws-bundle/${ICEBERG_VERSION}/iceberg-aws-bundle-${ICEBERG_VERSION}.jar" && \
    curl -fSL -o /opt/bitnami/spark/jars/url-connection-client-${AWS_SDK_VERSION}.jar \
        "https://repo1.maven.org/maven2/software/amazon/awssdk/url-connection-client/${AWS_SDK_VERSION}/url-connection-client-${AWS_SDK_VERSION}.jar" && \
    chmod 644 /opt/bitnami/spark/jars/iceberg-*.jar \
              /opt/bitnami/spark/jars/url-connection-client-*.jar

# ---------------------------------------------------------------------------
# Spark defaults — Iceberg catalog configuration
# ---------------------------------------------------------------------------
# These defaults configure Spark to use an Iceberg REST catalog (Polaris)
# with S3 (MinIO) storage. They can be overridden at runtime via environment
# variables or spark-submit --conf flags.
COPY spark-defaults.conf /opt/bitnami/spark/conf/spark-defaults.conf

# ---------------------------------------------------------------------------
# Copy batch job scripts (schema evolution, compaction, etc.)
# ---------------------------------------------------------------------------
COPY jobs/ /opt/spark-jobs/
RUN chmod -R 755 /opt/spark-jobs/

# ---------------------------------------------------------------------------
# Install Python dependencies for PySpark jobs
# ---------------------------------------------------------------------------
COPY requirements.txt /tmp/spark-requirements.txt
RUN pip install --no-cache-dir -r /tmp/spark-requirements.txt && \
    rm /tmp/spark-requirements.txt

# Switch back to non-root user (bitnami convention)
USER 1001

# Health check for Spark master UI (only applies when SPARK_MODE=master)
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -sf http://localhost:8080/json/ || exit 1
