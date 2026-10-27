"""
OpenPACS Load Test Script
Simulates 10 concurrent users performing common operations.
Usage: python scripts/load_test.py

Measures:
- API response time (p50, p95, p99)
- Throughput (requests/second)
- Error rate
"""
import asyncio
import time
import statistics
import json
import httpx

BASE_URL = "https://his.example.org/pacs-api"
CONCURRENT_USERS = 10
REQUESTS_PER_USER = 20
RESULTS = []


async def login() -> str:
    """Get JWT token."""
    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.post(f"{BASE_URL}/api/v1/auth/login", json={
            "username": "admin", "password": "admin",
        })
        if resp.status_code == 200:
            return resp.json().get("access_token", "")
    return ""


async def timed_request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict:
    """Execute request and measure latency."""
    start = time.time()
    try:
        resp = await client.request(method, url, **kwargs)
        latency = (time.time() - start) * 1000  # ms
        return {"url": url, "status": resp.status_code, "latency_ms": latency, "error": None}
    except Exception as e:
        latency = (time.time() - start) * 1000
        return {"url": url, "status": 0, "latency_ms": latency, "error": str(e)}


async def simulate_user(user_id: int, token: str):
    """Simulate one user performing typical reading workflow."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, verify=False, timeout=30) as client:
        endpoints = [
            ("GET", "/health"),
            ("GET", "/api/v1/dashboard/today"),
            ("GET", "/api/v1/dashboard/reading-queue"),
            ("GET", "/api/v1/worklist"),
            ("GET", "/api/v1/worklist/stats"),
            ("GET", "/api/v1/reports"),
            ("GET", "/api/v1/templates"),
            ("GET", "/api/v1/ai/models"),
            ("GET", "/api/v1/dicomweb/studies"),
            ("GET", "/api/v1/audit?page=1&page_size=10"),
        ]

        for i in range(REQUESTS_PER_USER):
            method, path = endpoints[i % len(endpoints)]
            result = await timed_request(client, method, path)
            result["user_id"] = user_id
            RESULTS.append(result)
            await asyncio.sleep(0.1)  # Small delay between requests


async def main():
    print(f"OpenPACS Load Test")
    print(f"  Concurrent users: {CONCURRENT_USERS}")
    print(f"  Requests per user: {REQUESTS_PER_USER}")
    print(f"  Total requests: {CONCURRENT_USERS * REQUESTS_PER_USER}")
    print(f"  Target: {BASE_URL}")
    print()

    # Login
    token = await login()
    if not token:
        print("WARNING: Login failed, testing unauthenticated endpoints only")

    # Run concurrent users
    start = time.time()
    tasks = [simulate_user(i, token) for i in range(CONCURRENT_USERS)]
    await asyncio.gather(*tasks)
    total_time = time.time() - start

    # Analyze results
    latencies = [r["latency_ms"] for r in RESULTS if r["error"] is None]
    errors = [r for r in RESULTS if r["status"] >= 500 or r["error"]]
    success = [r for r in RESULTS if 200 <= r["status"] < 400]

    if latencies:
        sorted_lat = sorted(latencies)
        p50 = sorted_lat[int(len(sorted_lat) * 0.50)]
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
        p99 = sorted_lat[int(len(sorted_lat) * 0.99)]
        mean = statistics.mean(latencies)
    else:
        p50 = p95 = p99 = mean = 0

    rps = len(RESULTS) / total_time if total_time > 0 else 0
    error_rate = len(errors) / len(RESULTS) * 100 if RESULTS else 0

    print("=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"  Total requests:  {len(RESULTS)}")
    print(f"  Success:         {len(success)}")
    print(f"  Errors:          {len(errors)}")
    print(f"  Error rate:      {error_rate:.1f}%")
    print(f"  Duration:        {total_time:.1f}s")
    print(f"  Throughput:      {rps:.1f} req/s")
    print()
    print(f"  Latency (ms):")
    print(f"    Mean:          {mean:.0f}")
    print(f"    p50:           {p50:.0f}")
    print(f"    p95:           {p95:.0f}  {'✅ PASS' if p95 < 500 else '❌ FAIL'} (target: <500ms)")
    print(f"    p99:           {p99:.0f}")
    print(f"    Min:           {min(latencies):.0f}" if latencies else "")
    print(f"    Max:           {max(latencies):.0f}" if latencies else "")
    print("=" * 60)

    # Per-endpoint breakdown
    print("\n  Per-endpoint breakdown:")
    by_url = {}
    for r in RESULTS:
        url = r["url"]
        if url not in by_url:
            by_url[url] = []
        by_url[url].append(r["latency_ms"])

    for url, lats in sorted(by_url.items()):
        s = sorted(lats)
        p = s[int(len(s) * 0.95)] if len(s) > 1 else s[0]
        print(f"    {url:45s}  p95={p:6.0f}ms  n={len(lats)}")

    # Summary
    print(f"\n  SLA Assessment:")
    print(f"    API p95 < 500ms:  {'✅ PASS' if p95 < 500 else '❌ FAIL'} ({p95:.0f}ms)")
    print(f"    Error rate < 1%:  {'✅ PASS' if error_rate < 1 else '❌ FAIL'} ({error_rate:.1f}%)")
    print(f"    Throughput > 10:  {'✅ PASS' if rps > 10 else '❌ FAIL'} ({rps:.1f} req/s)")


if __name__ == "__main__":
    asyncio.run(main())
