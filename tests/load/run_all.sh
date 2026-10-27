#!/bin/bash
# OpenPACS Full Load Test Suite
# Usage: bash tests/load/run_all.sh [smoke|full]
#
# smoke: 5 users, 1 min (quick validation)
# full:  50 users, 5 min (production readiness)

set -e

MODE="${1:-smoke}"
RESULTS_DIR="tests/load/results/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULTS_DIR"

HOST="https://his.example.org"
export PACS_USERNAME="${PACS_USERNAME:-admin}"
export PACS_PASSWORD="${PACS_PASSWORD:-CHANGE_ME}"

echo "============================================"
echo "OpenPACS Load Test Suite - Mode: $MODE"
echo "Target: $HOST"
echo "Results: $RESULTS_DIR"
echo "============================================"

if [ "$MODE" = "smoke" ]; then
    USERS=5; SPAWN=1; DURATION="1m"; STUDIES=10; WS_CONN=10; WS_DUR=30
elif [ "$MODE" = "full" ]; then
    USERS=50; SPAWN=5; DURATION="5m"; STUDIES=50; WS_CONN=50; WS_DUR=120
else
    echo "Usage: $0 [smoke|full]"
    exit 1
fi

echo ""
echo "[1/3] API Load Test (Locust) - ${USERS} users, ${DURATION}"
echo "--------------------------------------------"
locust -f tests/load/locustfile.py \
    --host "$HOST" \
    --users "$USERS" \
    --spawn-rate "$SPAWN" \
    --run-time "$DURATION" \
    --headless \
    --csv "$RESULTS_DIR/api" \
    --html "$RESULTS_DIR/api_report.html" \
    2>&1 | tee "$RESULTS_DIR/api.log"

echo ""
echo "[2/3] Study Upload Test - ${STUDIES} studies"
echo "--------------------------------------------"
python tests/load/study_upload_test.py \
    --studies "$STUDIES" \
    --concurrent 5 \
    2>&1 | tee "$RESULTS_DIR/upload.log"

echo ""
echo "[3/3] WebSocket Test - ${WS_CONN} connections, ${WS_DUR}s"
echo "--------------------------------------------"
python tests/load/websocket_test.py \
    --connections "$WS_CONN" \
    --duration "$WS_DUR" \
    2>&1 | tee "$RESULTS_DIR/websocket.log"

echo ""
echo "============================================"
echo "All tests complete. Results in: $RESULTS_DIR"
echo "============================================"
