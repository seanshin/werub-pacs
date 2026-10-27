"""
WebSocket Concurrent Connection Test
======================================
Tests 50 concurrent WebSocket connections for notification streaming.

Usage:
    python tests/load/websocket_test.py
    python tests/load/websocket_test.py --connections 100 --duration 300

Requires: pip install websockets
"""

import argparse
import asyncio
import json
import os
import ssl
import statistics
import time
from dataclasses import dataclass, field

try:
    import websockets
except ImportError:
    print("Install websockets: pip install websockets")
    exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = os.getenv("PACS_BASE_URL", "https://his.example.org")
PACS_USERNAME = os.getenv("PACS_USERNAME", "admin")
PACS_PASSWORD = os.getenv("PACS_PASSWORD", "CHANGE_ME")

WS_URL = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")


@dataclass
class TestResult:
    total_connections: int = 0
    successful_connections: int = 0
    failed_connections: int = 0
    messages_received: int = 0
    connect_times: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    disconnections: int = 0


result = TestResult()


async def get_token() -> str | None:
    """Obtain JWT token via HTTP login."""
    import urllib.request

    url = f"{BASE_URL}/pacs-api/api/v1/auth/login"
    data = json.dumps({"username": PACS_USERNAME, "password": PACS_PASSWORD}).encode()

    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        resp = urllib.request.urlopen(req, context=ctx)
        body = json.loads(resp.read())
        return body.get("access_token")
    except Exception as e:
        print(f"Login failed: {e}")
        return None


async def ws_client(client_id: int, token: str, duration: int):
    """Single WebSocket client that connects and listens for messages."""
    ws_endpoint = f"{WS_URL}/pacs-api/ws/notifications?token={token}"
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    start = time.time()
    result.total_connections += 1

    try:
        connect_start = time.time()
        async with websockets.connect(
            ws_endpoint,
            ssl=ssl_ctx,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            connect_time = (time.time() - connect_start) * 1000
            result.connect_times.append(connect_time)
            result.successful_connections += 1

            end_time = time.time() + duration
            while time.time() < end_time:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    result.messages_received += 1
                except asyncio.TimeoutError:
                    # No message, send ping to keep alive
                    try:
                        pong = await ws.ping()
                        await asyncio.wait_for(pong, timeout=5.0)
                    except Exception:
                        result.disconnections += 1
                        return
                except websockets.exceptions.ConnectionClosed:
                    result.disconnections += 1
                    return

    except Exception as e:
        result.failed_connections += 1
        result.errors.append(f"Client {client_id}: {type(e).__name__}: {e}")


async def run_test(num_connections: int, duration: int):
    """Run WebSocket concurrent connection test."""
    print(f"WebSocket Load Test: {num_connections} connections x {duration}s")
    print("-" * 60)

    token = await get_token()
    if not token:
        print("FAIL: Could not obtain auth token")
        return

    print(f"Token obtained. Launching {num_connections} connections...")

    tasks = [ws_client(i, token, duration) for i in range(num_connections)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Report
    print("\n" + "=" * 60)
    print("WebSocket Load Test Results")
    print("=" * 60)
    print(f"Total attempted:     {result.total_connections}")
    print(f"Successful connects: {result.successful_connections}")
    print(f"Failed connects:     {result.failed_connections}")
    print(f"Disconnections:      {result.disconnections}")
    print(f"Messages received:   {result.messages_received}")

    if result.connect_times:
        print(f"Connect time avg:    {statistics.mean(result.connect_times):.0f}ms")
        print(f"Connect time p95:    {sorted(result.connect_times)[int(len(result.connect_times)*0.95)]:.0f}ms")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for err in result.errors[:10]:
            print(f"  - {err}")

    # Pass/Fail
    success_rate = result.successful_connections / max(result.total_connections, 1)
    disconnect_rate = result.disconnections / max(result.successful_connections, 1)

    issues = []
    if success_rate < 0.95:
        issues.append(f"Connection success rate {success_rate*100:.1f}% < 95%")
    if disconnect_rate > 0.1:
        issues.append(f"Disconnect rate {disconnect_rate*100:.1f}% > 10%")

    print("\n" + ("RESULT: FAIL - " + "; ".join(issues) if issues else "RESULT: PASS"))
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="WebSocket load test")
    parser.add_argument("--connections", type=int, default=50)
    parser.add_argument("--duration", type=int, default=120, help="Duration in seconds")
    args = parser.parse_args()

    asyncio.run(run_test(args.connections, args.duration))


if __name__ == "__main__":
    main()
