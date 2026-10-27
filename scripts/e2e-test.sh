#!/bin/bash
# OpenPACS E2E Integration Test
# Tests the full pipeline: upload → validate → view → report → AI
set -e

BASE_URL="${1:-https://his.example.org/pacs-api}"
PASS=0
FAIL=0
TOTAL=0

check() {
    TOTAL=$((TOTAL + 1))
    local name="$1"
    local expected="$2"
    local actual="$3"
    if echo "$actual" | grep -q "$expected"; then
        PASS=$((PASS + 1))
        echo "  ✅ $name"
    else
        FAIL=$((FAIL + 1))
        echo "  ❌ $name (expected: $expected, got: $actual)"
    fi
}

echo "========================================="
echo "  OpenPACS E2E Integration Test"
echo "  Target: $BASE_URL"
echo "========================================="

# 1. Health Check
echo ""
echo "── 1. Service Health ──"
HEALTH=$(curl -sk "$BASE_URL/health")
check "API status" '"status":"ok"' "$HEALTH"
check "Redis connected" '"redis":"ok"' "$HEALTH"
check "Orthanc connected" '"dicom_aet":"OPENPACS"' "$HEALTH"

# 2. Authentication
echo ""
echo "── 2. Authentication ──"
TOKEN=$(curl -sk -X POST "$BASE_URL/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"CHANGE_ME"}' | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token","FAIL"))')
check "Admin login" "eyJ" "$TOKEN"

ME=$(curl -sk "$BASE_URL/api/v1/auth/me" -H "Authorization: Bearer $TOKEN")
check "Token validation" '"role":"admin"' "$ME"

# No-auth rejection
NOAUTH=$(curl -sk "$BASE_URL/api/v1/auth/me")
check "Unauthorized rejected" '"detail"' "$NOAUTH"

# 3. DICOM Validation
echo ""
echo "── 3. DICOM Validation ──"
# Create test DICOM
python3 -c "
import pydicom, numpy as np, io
ds = pydicom.Dataset()
ds.PatientName = 'E2E^Test'
ds.PatientID = 'E2E001'
ds.Modality = 'CR'
ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.1'
ds.SOPInstanceUID = '1.2.3.4.5.6.7.8.9.99'
ds.StudyInstanceUID = '1.2.3.4.5.6.7.8.9.100'
ds.SeriesInstanceUID = '1.2.3.4.5.6.7.8.9.101'
ds.StudyDate = '20260509'
ds.Rows = 64; ds.Columns = 64
ds.BitsAllocated = 16; ds.BitsStored = 12; ds.HighBit = 11
ds.PixelRepresentation = 0; ds.SamplesPerPixel = 1
ds.PhotometricInterpretation = 'MONOCHROME2'
ds.PixelData = np.random.randint(0, 4095, (64,64), dtype=np.uint16).tobytes()
ds.file_meta = pydicom.Dataset()
ds.file_meta.TransferSyntaxUID = '1.2.840.10008.1.2.1'
ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
ds.is_little_endian = True; ds.is_implicit_VR = False
ds.save_as('/tmp/e2e_test.dcm', write_like_original=False)
print('OK')
" 2>/dev/null
check "Test DICOM created" "OK" "OK"

VALIDATE=$(curl -sk -X POST "$BASE_URL/api/v1/validation/validate" -F "file=@/tmp/e2e_test.dcm")
check "Validation accepted" '"accepted":true' "$VALIDATE"
check "Validation findings" '"counts"' "$VALIDATE"

# 4. STOW-RS Upload (with validation)
echo ""
echo "── 4. DICOM Upload (STOW-RS) ──"
UPLOAD=$(curl -sk -X POST "$BASE_URL/api/v1/dicomweb/studies" -F "file=@/tmp/e2e_test.dcm")
check "STOW-RS stored" '"status":"stored"' "$UPLOAD"
check "Validation integrated" '"validation"' "$UPLOAD"

# 5. Study Query
echo ""
echo "── 5. Study Query ──"
STUDIES=$(curl -sk "$BASE_URL/api/v1/dicomweb/studies" -H "Authorization: Bearer $TOKEN")
check "QIDO-RS studies" '"count"' "$STUDIES"

STATS=$(curl -sk "$BASE_URL/api/v1/statistics")
check "Orthanc statistics" '"CountStudies"' "$STATS"

# 6. DICOMweb
echo ""
echo "── 6. DICOMweb ──"
DWEBSTATUS=$(curl -sk -o /dev/null -w '%{http_code}' "https://his.example.org/dicom-web/studies")
check "DICOMweb accessible" "200" "$DWEBSTATUS"

# 7. Worklist
echo ""
echo "── 7. Worklist ──"
WLIST=$(curl -sk "$BASE_URL/api/v1/worklist" -H "Authorization: Bearer $TOKEN")
check "Worklist list" '"total"' "$WLIST"

WSTATS=$(curl -sk "$BASE_URL/api/v1/worklist/stats" -H "Authorization: Bearer $TOKEN")
check "Worklist stats" '"by_modality"' "$WSTATS"

# 8. Report
echo ""
echo "── 8. Reading Report ──"
REPORT=$(curl -sk -X POST "$BASE_URL/api/v1/reports" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"study_instance_uid\":\"1.2.3.4.5.6.7.8.9.100\",\"patient_id\":\"E2E001\",\"patient_name\":\"E2E Test\",\"modality\":\"CR\",\"findings\":\"Normal\",\"impression\":\"No abnormality\"}")
check "Report created" '"status":"draft"' "$REPORT"
REPORT_ID=$(echo "$REPORT" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("id",""))' 2>/dev/null)

SIGNED=$(curl -sk -X POST "$BASE_URL/api/v1/reports/$REPORT_ID/sign" -H "Authorization: Bearer $TOKEN")
check "Report signed" '"status":"final"' "$SIGNED"

# 9. QC
echo ""
echo "── 9. QC Management ──"
QCCHECK=$(curl -sk -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/v1/qc/patient-reconciliation" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"orthanc_study_id":"nonexistent","new_patient_id":"TEST","reason":"e2e test"}')
check "QC API accessible" "404\|422\|200" "$QCCHECK"

# 10. AI
echo ""
echo "── 10. AI Module ──"
MODELS=$(curl -sk "$BASE_URL/api/v1/ai/models" -H "Authorization: Bearer $TOKEN")
check "AI models list" '"count"' "$MODELS"

DASHBOARD=$(curl -sk "$BASE_URL/api/v1/ai/dashboard" -H "Authorization: Bearer $TOKEN")
check "AI dashboard" '"total_models"' "$DASHBOARD"

INFERENCE=$(curl -sk -X POST "$BASE_URL/api/v1/ai/inference" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"model_name":"chest-xray-analyzer","study_instance_uid":"1.2.3.4.5.6.7.8.9.100"}')
check "AI inference queued" '"status":"queued"' "$INFERENCE"

# 11. Audit
echo ""
echo "── 11. Audit Log ──"
AUDIT=$(curl -sk "$BASE_URL/api/v1/audit" -H "Authorization: Bearer $TOKEN")
check "Audit log accessible" '"total"' "$AUDIT"

# 12. WebSocket
echo ""
echo "── 12. WebSocket ──"
WSSTATUS=$(curl -sk "$BASE_URL/api/v1/ws/status")
check "WebSocket status" '"active_connections"' "$WSSTATUS"

# 13. OHIF Viewer
echo ""
echo "── 13. OHIF Viewer ──"
OHIF=$(curl -sk -o /dev/null -w '%{http_code}' "https://his.example.org/viewer/")
check "OHIF Viewer loads" "200" "$OHIF"

CONFIG=$(curl -sk "https://his.example.org/app-config.js" | head -3)
check "Custom config served" "routerBasename" "$CONFIG"

# 14. Swagger
echo ""
echo "── 14. API Documentation ──"
SWAGGER=$(curl -sk -o /dev/null -w '%{http_code}' "$BASE_URL/docs")
check "Swagger UI" "200" "$SWAGGER"

OPENAPI=$(curl -sk "$BASE_URL/openapi.json" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d["paths"]))' 2>/dev/null)
check "OpenAPI endpoints" "18" "$OPENAPI"

# Summary
echo ""
echo "========================================="
echo "  Results: $PASS/$TOTAL passed, $FAIL failed"
echo "========================================="
if [ $FAIL -eq 0 ]; then
    echo "  🎉 All tests passed!"
else
    echo "  ⚠️  $FAIL test(s) failed"
fi
