
> [!NOTE]
> Replace `localhost` with your machine's IP address if necessary.

# Version Check

### 🛠 Versions

| Software | Version | Repository / Base Image |
| --- | --- | --- |
| **Apache Polaris** | `1.3.0-incubating` | `apache/polaris` |
| **MinIO** | `2025-09-07T16-13-09Z` | `quay.io/minio/minio` |
| **Trino** | `479` | `trinodb/trino` |

---

### 🔍 How to Verify Versions

You can verify the installed software versions using the following commands:

1. **Apache Polaris**

    Check the container logs or health endpoint.
    ```bash
    docker logs polaris
    curl http://localhost:8182/healthcheck
    ```

2. **MinIO**

    Execute the version command inside the MinIO container to check the specific release tag.

    ```bash
    docker exec -it minio minio --version
    ```

3. **Trino**

    Check the Trino version via CLI or Web UI.

    ```bash
    docker exec -it trino trino --execute "SELECT version()"
    ```

---

# Start Iceberg Lakehouse

0. **Clone the repository**
    ```bash
    git clone <REPO>
    cd <REPO>
    ```

1.  **Create a `.env` file**
    ```bash
    cp example.env .env
    ```
      - Refer to the `example.env` file for configuration.
    > [!NOTE]
    > The `MINIO_ROOT_USER` and `AWS_ACCESS_KEY_ID`, as well as the `MINIO_ROOT_PASSWORD` and `AWS_SECRET_ACCESS_KEY` in the `.env` file, must match each other.
    >
    > The USER must be at least 5 characters long, and the PASSWORD must be at least 8 characters long.
    >
    > `POLARIS_ROOT_CLIENT_ID` and `POLARIS_ROOT_CLIENT_SECRET` are the bootstrap credentials for the Polaris catalog.

2.  **Grant execution permissions and run `start.sh`**

    ```bash
    chmod +x start.sh
    ./start.sh
    ```

3.  **Create a `warehouse` bucket in MinIO** (Required for Iceberg table storage)

    You can create the required `warehouse` bucket using either the Web UI or the Container CLI.

    #### **Option A: Via Web UI (Recommended for GUI users)**

    1. **Access the Console:** Open http://localhost:9001 in your browser.
    2. **Login:** Use the `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` defined in your `.env` file.
    3. **Create Bucket:** Click on **'Buckets'** -> **'Create Bucket'** and name it `warehouse`.

    #### **Option B: Via Container CLI (Recommended for terminal users)**

    1. **Access the MinIO container:**
        ```bash
        docker exec -it minio bash
        ```

    2. **Configure alias and create the bucket:**
        ```bash
        # Use the credentials from your .env file
        mc alias set local http://localhost:9000 admin password
        mc mb local/warehouse
        ```
    3. **Check created bucket**
       ```bash
       mc ls local
       ```

---

4.  **Create a Polaris catalog**

    After Polaris is running, create an Iceberg catalog via the management API:

    ```bash
    # 1. Get OAuth2 token
    TOKEN=$(curl -s -X POST http://localhost:8181/api/catalog/v1/oauth/tokens \
      -d "grant_type=client_credentials&client_id=${POLARIS_ROOT_CLIENT_ID}&client_secret=${POLARIS_ROOT_CLIENT_SECRET}&scope=PRINCIPAL_ROLE:ALL" \
      | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

    # 2. Create catalog
    curl -s -X POST http://localhost:8181/api/management/v1/catalogs \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "catalog": {
          "name": "iceberg",
          "type": "INTERNAL",
          "storageConfigInfo": {
            "storageType": "S3",
            "allowedLocations": ["s3://warehouse/"]
          },
          "properties": {
            "default-base-location": "s3://warehouse/"
          }
        }
      }'
    ```

5.  **Access the Trino CLI**

    ```bash
    docker exec -it trino trino
    ```

6.  **Run the environment setup test**

    ```sql
    -- Inside Trino CLI
    SHOW CATALOGS;
    CREATE SCHEMA IF NOT EXISTS iceberg.db;
    CREATE TABLE IF NOT EXISTS iceberg.db.demo (id BIGINT, data VARCHAR);
    INSERT INTO iceberg.db.demo VALUES (1, 'a'), (2, 'b');
    SELECT * FROM iceberg.db.demo;
    ```

7.  **Monitor Trino Queries**

      - Access the Trino Web UI: http://localhost:8443

8.  **Verify data in MinIO Console**

      - Access: http://localhost:9001
      - Check the `warehouse` bucket to see if data has been created.

> [!NOTE]
> The MinIO data is stored in the `minio_data` folder within the directory where the Docker Compose command is executed, so the data is preserved even if the containers are removed and restarted.
