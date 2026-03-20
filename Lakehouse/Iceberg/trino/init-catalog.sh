#!/bin/bash
# -------------------------------------------------------------------
# Trino Iceberg catalog properties initializer
#
# Renders iceberg.properties from the .template file using
# environment variables injected by docker-compose.
# This avoids hardcoding credentials in the properties file.
#
# Usage: Executed as a Docker entrypoint wrapper.
# -------------------------------------------------------------------
set -e

TEMPLATE="/etc/trino/catalog/iceberg.properties.template"
OUTPUT="/etc/trino/catalog/iceberg.properties"

# Provide defaults so substitution never produces empty values
POLARIS_CREDENTIAL="${POLARIS_CREDENTIAL:-root:s3cr3t00}"
ICEBERG_WAREHOUSE="${ICEBERG_WAREHOUSE:-iceberg2}"
AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-admin}"
AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-admin1234}"

if [ -f "$TEMPLATE" ]; then
    # Use sed instead of envsubst (not available in Trino image)
    sed \
        -e "s|\${POLARIS_CREDENTIAL}|${POLARIS_CREDENTIAL}|g" \
        -e "s|\${ICEBERG_WAREHOUSE}|${ICEBERG_WAREHOUSE}|g" \
        -e "s|\${AWS_ACCESS_KEY_ID}|${AWS_ACCESS_KEY_ID}|g" \
        -e "s|\${AWS_SECRET_ACCESS_KEY}|${AWS_SECRET_ACCESS_KEY}|g" \
        "$TEMPLATE" > "$OUTPUT"
    echo "[init-catalog] Rendered $OUTPUT from template"
else
    echo "[init-catalog] WARNING: Template not found at $TEMPLATE, using existing properties"
fi

# Hand off to Trino's original entrypoint
exec /usr/lib/trino/bin/run-trino "$@"
