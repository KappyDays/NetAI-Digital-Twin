"""Async-aware HTTP client for Lakehouse API using stdlib urllib only.

Uses asyncio.run_in_executor to avoid blocking the Isaac Sim UI thread.
Pattern borrowed from stagegraph.viewer/data_fetcher.py.
"""

import asyncio
import json
import urllib.error
import urllib.request


def api_get_sync(base_url: str, endpoint: str, timeout: int = 30) -> dict:
    """Synchronous GET request. Use inside run_in_executor."""
    url = f"{base_url.rstrip('/')}/{endpoint}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post_json_sync(base_url: str, endpoint: str, data: dict, timeout: int = 120) -> dict:
    """Synchronous POST JSON request. Use inside run_in_executor."""
    url = f"{base_url.rstrip('/')}/{endpoint}"
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def api_get(base_url: str, endpoint: str, timeout: int = 30) -> dict:
    """Non-blocking GET — runs in executor to avoid UI freeze."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: api_get_sync(base_url, endpoint, timeout)
    )


async def api_post_json(base_url: str, endpoint: str, data: dict, timeout: int = 120) -> dict:
    """Non-blocking POST JSON — runs in executor to avoid UI freeze."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: api_post_json_sync(base_url, endpoint, data, timeout)
    )
