#!/usr/bin/env bash
# 통합테스트 — Orthanc DICOM TLS DIMSE 종단 검증 (설치 제품 옵션 하드닝, 2026-07-14).
#
# 격리 throwaway Orthanc(TLS DIMSE, SQLite)를 띄우고, pynetdicom으로:
#   1) TLS C-ECHO (핸드셰이크만, CERT_NONE)      → TLS DIMSE 수신 가능
#   2) TLS C-ECHO (CA+hostname 검증, CERT_REQUIRED) → 발급 인증서가 체인·SAN까지 유효
#   3) 평문 접속                                  → TLS 전용 포트라 거부(TLS 강제 입증)
# 운영 Orthanc 무접촉. 완료 후 정리.
#
# 전제: 서버에서 실행. openpacs-backend(pynetdicom), docker, openssl.
#   ORTHANC_IMAGE 로 이미지 지정(기본 정본 compose와 동일 태그).
# ★함정: docker exec heredoc는 -i 필요(없으면 stdin 미전달 → 무출력).
set -uo pipefail

IMG="${ORTHANC_IMAGE:-orthancteam/orthanc:24.12.2}"
PORT="${TLS_TEST_PORT:-14242}"
H=orthanc-tlstest
IPSAN=127.0.0.1
TD=/tmp/dtls-test; rm -rf "$TD"; mkdir -p "$TD/tls"
FAIL=0
cleanup(){ docker rm -f "$H" >/dev/null 2>&1 || true; docker exec openpacs-backend rm -f /tmp/dtls-ca.pem 2>/dev/null || true; rm -rf "$TD"; }
trap cleanup EXIT

command -v openssl >/dev/null || { echo "openssl 필요"; exit 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || docker pull "$IMG" >/dev/null 2>&1 || { echo "SKIP: 이미지 $IMG 없음"; exit 0; }

# 1) 인증서 (CN/SAN=127.0.0.1)
openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
  -keyout "$TD/tls/ca-key.pem" -out "$TD/tls/ca-cert.pem" \
  -subj "/O=OpenPACS/CN=OpenPACS Internal CA" >/dev/null 2>&1
openssl req -newkey rsa:2048 -sha256 -nodes -keyout "$TD/tls/server-key.pem" \
  -subj "/O=OpenPACS/CN=$IPSAN" 2>/dev/null \
| openssl x509 -req -CA "$TD/tls/ca-cert.pem" -CAkey "$TD/tls/ca-key.pem" -CAcreateserial \
  -days 3650 -sha256 -out "$TD/tls/server-cert.pem" \
  -extfile <(printf "subjectAltName=IP:%s\nextendedKeyUsage=serverAuth,clientAuth\n" "$IPSAN") >/dev/null 2>&1
chmod 644 "$TD/tls/"*.pem
echo "PASS: 인증서 생성 (SAN=IP:$IPSAN)"

cat > "$TD/orthanc.json" <<JSON
{
  "Name": "TLSTEST", "DicomAet": "TLSTEST", "DicomPort": 4242, "HttpPort": 8042,
  "RemoteAccessAllowed": true, "AuthenticationEnabled": false,
  "DicomAlwaysAllowEcho": true, "DicomAlwaysAllowStore": true,
  "DicomTlsEnabled": true,
  "DicomTlsCertificate": "/etc/orthanc/tls/server-cert.pem",
  "DicomTlsPrivateKey": "/etc/orthanc/tls/server-key.pem",
  "DicomTlsTrustedCertificates": "/etc/orthanc/tls/ca-cert.pem",
  "DicomTlsRemoteCertificateRequired": false
}
JSON

docker rm -f "$H" >/dev/null 2>&1
docker run -d --name "$H" -p 127.0.0.1:$PORT:4242 \
  -v "$TD/orthanc.json:/etc/orthanc/orthanc.json:ro" \
  -v "$TD/tls:/etc/orthanc/tls:ro" "$IMG" >/dev/null || { echo "FAIL: 컨테이너 기동"; exit 1; }
for i in $(seq 1 40); do
  docker logs "$H" 2>&1 | grep -qiE "DICOM server listening|has started" && break; sleep 1
done
docker logs "$H" 2>&1 | grep -qiE "DICOM server listening" && echo "PASS: TLS Orthanc 기동" || { echo "FAIL: 기동 로그"; exit 1; }

# 2) backend(pynetdicom)에서 TLS C-ECHO (★docker exec -i)
docker cp "$TD/tls/ca-cert.pem" openpacs-backend:/tmp/dtls-ca.pem
OUT="$(docker exec -i openpacs-backend python - "$PORT" <<'PY'
import sys, ssl
from pynetdicom import AE
from pynetdicom.sop_class import Verification
port=int(sys.argv[1]); host='127.0.0.1'
def echo(tag, ctx, sni):
    ae=AE(); ae.add_requested_context(Verification)
    try: a=ae.associate(host,port,ae_title='TLSTEST',tls_args=(ctx,sni))
    except Exception as e: print(f"{tag}=EXC"); return
    if a.is_established:
        st=a.send_c_echo(); a.release(); print(f"{tag}={'OK' if st and int(st.Status)==0 else 'ECHOFAIL'}")
    else: print(f"{tag}=ASSOCFAIL")
c1=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); c1.check_hostname=False; c1.verify_mode=ssl.CERT_NONE
echo("NONE",c1,None)
c2=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); c2.load_verify_locations('/tmp/dtls-ca.pem')
c2.check_hostname=True; c2.verify_mode=ssl.CERT_REQUIRED
echo("VERIFY",c2,'127.0.0.1')
ae=AE(); ae.add_requested_context(Verification)
try:
    a=ae.associate(host,port,ae_title='TLSTEST')
    print("PLAIN=ESTABLISHED" if a.is_established else "PLAIN=REJECTED")
    if a.is_established: a.release()
except Exception: print("PLAIN=REJECTED")
PY
)"
echo "$OUT" | grep -q "NONE=OK"     && echo "PASS: TLS C-ECHO (CERT_NONE 핸드셰이크)"      || { echo "FAIL: TLS C-ECHO NONE ($OUT)"; FAIL=1; }
echo "$OUT" | grep -q "VERIFY=OK"   && echo "PASS: TLS C-ECHO (CA+hostname 검증)"          || { echo "FAIL: TLS C-ECHO VERIFY ($OUT)"; FAIL=1; }
echo "$OUT" | grep -q "PLAIN=REJECTED" && echo "PASS: 평문 접속 거부(TLS 전용 강제)"        || { echo "FAIL: 평문 접속 미거부 ($OUT)"; FAIL=1; }

[ "$FAIL" = 0 ] && echo "=== IT PASS: DICOM TLS DIMSE 종단 검증 완료 ===" || { echo "=== IT FAIL ==="; exit 1; }
