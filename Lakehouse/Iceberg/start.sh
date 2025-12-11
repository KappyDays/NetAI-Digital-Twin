#!/bin/bash

mkdir -p ./nessie_data
mkdir -p ./minio_data
mkdir -p ./jars
mkdir -p ./python-scripts

chmod -R 777 ./nessie_data
chmod -R 777 ./minio_data
chmod -R 777 ./jars
chmod -R 777 ./python-scripts

# Download JAR file (Prevents Docker from creating an empty directory which causes errors)
JAR_URL="https://repo1.maven.org/maven2/org/projectnessie/nessie-integrations/nessie-spark-extensions-3.5_2.12/0.106.0/nessie-spark-extensions-3.5_2.12-0.106.0.jar"
JAR_FILE="./jars/nessie-spark-extensions-3.5_2.12-0.106.0.jar"

if [ -f "$JAR_FILE" ]; then
    echo -e "${GREEN} -> JAR file already exists. Skipping download.${NC}"
else
    echo -e " -> Starting JAR file download..."
    # Use wget if available, otherwise use curl
    if command -v wget &> /dev/null; then
        wget -q --show-progress -O "$JAR_FILE" "$JAR_URL"
    elif command -v curl &> /dev/null; then
        curl -L -o "$JAR_FILE" "$JAR_URL"
    else
        echo -e "${RED}Error: Neither wget nor curl found. Please download the JAR file manually.${NC}"
        exit 1
    fi
    echo -e "${GREEN} -> JAR file download complete${NC}"
fi

docker-compose up -d

echo -e " - Nessie  : http://localhost:19120"
echo -e " - MinIO   : http://localhost:9001 (ID: AAAAA / PW: BBBBBBBB)"
echo -e " - Spark UI: http://localhost:4040 (Activated when the job runs)"

docker-compose ps