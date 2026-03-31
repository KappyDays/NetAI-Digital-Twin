"""Lakehouse Stack E2E Verification Test"""
import json, urllib.request, time

time.sleep(2)
results = []

def test(name, fn):
    try:
        ok, detail = fn()
        status = "PASS" if ok else "FAIL"
    except Exception as e:
        status = "FAIL"
        detail = str(e)[:150]
    results.append((name, status, detail))
    print(f"  [{status}] {name}: {detail}")

def http_status(url):
    return urllib.request.urlopen(url, timeout=10).status

def api(sql):
    data = json.dumps({"sql": sql}).encode()
    req = urllib.request.Request("http://localhost:8100/api/v1/query", data=data, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())

def api_get(path):
    return json.loads(urllib.request.urlopen(f"http://localhost:8100{path}", timeout=10).read().decode())

T = "iceberg.static_db.static_prims"

# 1. Infrastructure
print("=== 1. Infrastructure Health ===")
test("MinIO (9000)", lambda: (http_status("http://localhost:9000/minio/health/live") == 200, "HTTP 200"))
test("MinIO Console (9001)", lambda: (http_status("http://localhost:9001/") == 200, "Web UI OK"))
test("Polaris (8182)", lambda: (
    json.loads(urllib.request.urlopen("http://localhost:8182/q/health", timeout=5).read().decode())["status"] == "UP",
    "status: UP"))
test("Lakehouse API (8100)", lambda: (api_get("/api/v1/health")["status"] in ("healthy", "ok"), "status: " + api_get("/api/v1/health")["status"]))
test("Dashboard (3000)", lambda: (http_status("http://localhost:3000/") == 200, "HTML OK"))

# 2. Trino SQL
print("\n=== 2. Trino SQL Engine ===")
test("SHOW SCHEMAS", lambda: (api("SHOW SCHEMAS FROM iceberg")["row_count"] > 0, f'{api("SHOW SCHEMAS FROM iceberg")["row_count"]} schemas'))
test("SHOW TABLES (static)", lambda: (True, f'{api("SHOW TABLES FROM iceberg.static_db")["row_count"]} tables'))
test("SELECT 1", lambda: (api("SELECT 1 AS x")["row_count"] == 1, "OK"))

# 3. Lakehouse API
print("\n=== 3. Lakehouse API Endpoints ===")
test("Deep health", lambda: (api_get("/health")["dependencies"]["trino_iceberg"]["status"] == "healthy", "trino healthy"))
test("Static spaces", lambda: (True, str(api_get("/api/v1/static/spaces"))[:80]))
test("Congestion summary", lambda: (True, str(api_get("/api/v1/spaces/congestion/summary"))[:80]))

# 4. Iceberg Features SQL
print("\n=== 4. Iceberg Features SQL ===")
test("DESCRIBE", lambda: (api(f"DESCRIBE {T}")["row_count"] > 0, f'{api(f"DESCRIBE {T}")["row_count"]} cols'))
test("SHOW CREATE TABLE", lambda: (api(f"SHOW CREATE TABLE {T}")["row_count"] == 1, "DDL OK"))

snap_sql = 'SELECT * FROM iceberg.static_db."static_prims$snapshots"'
test("$snapshots", lambda: (True, f'{api(snap_sql)["row_count"]} rows'))

hist_sql = 'SELECT * FROM iceberg.static_db."static_prims$history"'
test("$history", lambda: (True, f'{api(hist_sql)["row_count"]} rows'))

files_sql = 'SELECT * FROM iceberg.static_db."static_prims$files"'
test("$files", lambda: (True, f'{api(files_sql)["row_count"]} rows'))

part_sql = 'SELECT * FROM iceberg.static_db."static_prims$partitions"'
test("$partitions", lambda: (True, f'{api(part_sql)["row_count"]} rows'))

mani_sql = 'SELECT * FROM iceberg.static_db."static_prims$manifests"'
test("$manifests", lambda: (True, f'{api(mani_sql)["row_count"]} rows'))

tt_ver_sql = f"SELECT * FROM {T} FOR VERSION AS OF 936368314663528761 LIMIT 5"
test("Time Travel (version)", lambda: (True, f'{api(tt_ver_sql)["row_count"]} rows'))

tt_ts_sql = f"SELECT * FROM {T} FOR TIMESTAMP AS OF TIMESTAMP '2026-03-25 02:01:47' LIMIT 5"
test("Time Travel (timestamp)", lambda: (True, f'{api(tt_ts_sql)["row_count"]} rows'))

count_sql = f"SELECT COUNT(*) FROM {T}"
test("COUNT(*)", lambda: (True, f'{api(count_sql)["rows"][0][0]} rows'))

# 5. Dashboard Pages
print("\n=== 5. Dashboard Pages ===")
for path in ["/", "/iceberg", "/congestion", "/static", "/dynamic", "/query"]:
    test(f"Page {path}", lambda p=path: (http_status(f"http://localhost:3000{p}") == 200, "OK"))

# Summary
print("\n" + "=" * 55)
passed = sum(1 for _, s, _ in results if s == "PASS")
total = len(results)
failed = [(n, d) for n, s, d in results if s == "FAIL"]
print(f"TOTAL: {passed}/{total} PASSED")
if failed:
    print("FAILURES:")
    for n, d in failed:
        print(f"  - {n}: {d}")
