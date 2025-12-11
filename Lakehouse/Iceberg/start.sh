#!/bin/bash

mkdir -p ./nessie_data
mkdir -p ./minio_data
mkdir -p ./jars
mkdir -p ./python-scripts

docker-compose up -d

echo -e " - Nessie  : http://localhost:19120"
echo -e " - MinIO   : http://localhost:9001 (ID: AAAAA / PW: BBBBBBBB)"
echo -e " - Spark UI: http://localhost:4040 (Activated when the job runs)"

docker-compose ps