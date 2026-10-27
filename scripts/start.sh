#!/bin/bash
# OpenPACS - Start all services
set -e

echo "========================================="
echo "  OpenPACS - Starting all services"
echo "========================================="

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed."
    echo "Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
    exit 1
fi

# Check Docker Compose
if ! docker compose version &> /dev/null; then
    echo "ERROR: Docker Compose is not available."
    exit 1
fi

# Check .env file
if [ ! -f .env ]; then
    echo "ERROR: .env file not found. Copy from .env.example and edit."
    exit 1
fi

echo ""
echo "[1/3] Building backend image..."
docker compose build backend

echo ""
echo "[2/3] Starting all services..."
docker compose up -d

echo ""
echo "[3/3] Waiting for services to be healthy..."
sleep 5

echo ""
echo "========================================="
echo "  Service URLs"
echo "========================================="
echo "  Nginx (Gateway):    http://localhost:80"
echo "  Orthanc Explorer:   http://localhost:8042  (admin / changeme_orthanc_2026)"
echo "  FastAPI Docs:       http://localhost:8000/docs"
echo "  Keycloak Admin:     http://localhost:8080  (admin / changeme_keycloak_2026)"
echo "  Prometheus:         http://localhost:9090"
echo "  Grafana:            http://localhost:3000  (admin / changeme_grafana_2026)"
echo ""
echo "  DICOM Port:         localhost:4242  (AE Title: OPENPACS)"
echo "========================================="
echo ""
echo "Check status:  docker compose ps"
echo "View logs:     docker compose logs -f"
echo "Stop:          docker compose down"
