#!/usr/bin/env bash
# DICOM TLS 인증서 생성 — 설치 제품(standalone) 옵션 하드닝.
#
# 클리닉 모달리티망에서 C-STORE/FIND/MOVE(4242)를 평문 대신 TLS로 암호화하려는 경우 사용.
# 자체서명 CA + 서버 인증서(Orthanc용)를 생성한다. 상호 TLS(모달리티도 클라이언트 인증서 제출)를
# 쓰려면 각 모달리티용 클라이언트 인증서도 --client 로 발급해 CA를 신뢰시키면 된다.
#
# 사용:
#   ./gen-dicom-tls.sh <orthanc-host-or-ip> [outdir]        # CA + 서버 인증서
#   ./gen-dicom-tls.sh --client <modality-name> [outdir]    # 클라이언트(모달리티) 인증서(상호 TLS용)
#
# 기본 outdir: docker/orthanc/tls (compose가 /etc/orthanc/tls로 마운트).
# 멱등: 이미 있으면 덮어쓰지 않음(--force 로 재발급).
set -euo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/../.." && pwd)"
DAYS=3650                       # 10년(내부 CA)
FORCE=0
MODE="server"
CLIENT_NAME=""

args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --client) MODE="client"; CLIENT_NAME="${2:-}"; shift 2 ;;
    *) args+=("$1"); shift ;;
  esac
done
set -- "${args[@]:-}"

# 위치 인자: server 모드는 <host> [outdir], client 모드는 --client <name>이 소비돼 [outdir]만 남음
if [ "$MODE" = "client" ]; then
  OUTDIR="${1:-$REPO_ROOT/docker/orthanc/tls}"
else
  OUTDIR="${2:-$REPO_ROOT/docker/orthanc/tls}"
fi
mkdir -p "$OUTDIR"
CA_KEY="$OUTDIR/ca-key.pem"
CA_CERT="$OUTDIR/ca-cert.pem"

info(){ echo "[gen-dicom-tls] $*"; }
die(){ echo "[gen-dicom-tls] ERROR: $*" >&2; exit 1; }
command -v openssl >/dev/null || die "openssl 필요"

# --- 1) 내부 CA (없으면 생성) ---
if [ ! -f "$CA_CERT" ] || [ "$FORCE" = 1 ]; then
  info "내부 CA 생성 → $CA_CERT"
  openssl req -x509 -newkey rsa:4096 -sha256 -days "$DAYS" -nodes \
    -keyout "$CA_KEY" -out "$CA_CERT" \
    -subj "/O=OpenPACS/OU=DICOM-TLS/CN=OpenPACS Internal CA" >/dev/null 2>&1
  chmod 600 "$CA_KEY"
else
  info "기존 CA 재사용 → $CA_CERT (재발급하려면 --force)"
fi

if [ "$MODE" = "client" ]; then
  [ -n "$CLIENT_NAME" ] || die "--client 뒤에 모달리티 이름 필요"
  CK="$OUTDIR/client-${CLIENT_NAME}-key.pem"
  CC="$OUTDIR/client-${CLIENT_NAME}-cert.pem"
  if [ -f "$CC" ] && [ "$FORCE" != 1 ]; then
    die "클라이언트 인증서 이미 존재: $CC (재발급하려면 --force)"
  fi
  info "클라이언트(모달리티) 인증서 발급: $CLIENT_NAME"
  openssl req -newkey rsa:2048 -sha256 -nodes -keyout "$CK" \
    -subj "/O=OpenPACS/OU=Modality/CN=${CLIENT_NAME}" 2>/dev/null \
  | openssl x509 -req -CA "$CA_CERT" -CAkey "$CA_KEY" -CAcreateserial \
      -days "$DAYS" -sha256 -out "$CC" >/dev/null 2>&1
  chmod 600 "$CK"
  info "완료: $CC (모달리티에 이 키/인증서 설치, Orthanc는 CA로 신뢰 — 상호 TLS 시)"
  exit 0
fi

# --- 2) 서버 인증서 (Orthanc) ---
HOST="${1:-}"
[ -n "$HOST" ] || die "Orthanc 호스트명/IP 인자 필요 (예: pacs.clinic.local 또는 192.168.1.10)"
SRV_KEY="$OUTDIR/server-key.pem"
SRV_CERT="$OUTDIR/server-cert.pem"
if [ -f "$SRV_CERT" ] && [ "$FORCE" != 1 ]; then
  die "서버 인증서 이미 존재: $SRV_CERT (재발급하려면 --force)"
fi

# SAN: IP면 IP:, 아니면 DNS:
if echo "$HOST" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
  SAN="IP:$HOST"
else
  SAN="DNS:$HOST"
fi
info "서버 인증서 발급: CN=$HOST (SAN=$SAN)"
openssl req -newkey rsa:2048 -sha256 -nodes -keyout "$SRV_KEY" \
  -subj "/O=OpenPACS/OU=DICOM/CN=${HOST}" 2>/dev/null \
| openssl x509 -req -CA "$CA_CERT" -CAkey "$CA_KEY" -CAcreateserial \
    -days "$DAYS" -sha256 -out "$SRV_CERT" \
    -extfile <(printf "subjectAltName=%s\nextendedKeyUsage=serverAuth,clientAuth\n" "$SAN") >/dev/null 2>&1
chmod 600 "$SRV_KEY"

info "완료. 생성물($OUTDIR):"
info "  ca-cert.pem       — 내부 CA(모달리티에 신뢰 등록)"
info "  server-cert.pem   — Orthanc 서버 인증서"
info "  server-key.pem    — Orthanc 서버 개인키"
info ""
info "다음: .env 에 ORTHANC_DICOM_TLS_ENABLED=true 설정 후 orthanc 재기동."
info "상호 TLS(모달리티 인증서 요구): ORTHANC_DICOM_TLS_MUTUAL=true + 모달리티마다 --client 발급."
