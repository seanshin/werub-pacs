import sys, time, json, base64, subprocess
import urllib.request, urllib.error
from jose import jwt
from cryptography.fernet import Fernet
import io, zipfile

SECRET = "change-me-to-a-random-string-at-least-32-chars"  # container's actual value
BASE = "https://his.example.org/pacs-api"
GATEWAY = "https://his.example.org"
MRN = sys.argv[1]

def tok(mrn): return jwt.encode({"scope":"patient-export","mrn":mrn,"iss":"patient-portal","exp":int(time.time())+600}, SECRET, algorithm="HS256")

def req(method, url, token=None, body=None):
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method)
    if token: r.add_header("Authorization", f"Bearer {token}")
    if body: r.add_header("Content-Type","application/json")
    try:
        resp = urllib.request.urlopen(r, timeout=30)
        return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

# 1) 요청
st, b = req("POST", f"{BASE}/api/v1/patient-export/requests", tok(MRN), {"mrn":MRN,"purpose":"patient_view"})
print("1) create:", st, b[:120].decode())
rid = json.loads(b)["request_id"]

# 2) 폴링
for _ in range(30):
    st, b = req("GET", f"{BASE}/api/v1/patient-export/requests/{rid}", tok(MRN))
    j = json.loads(b)
    if j["status"] in ("ready","failed","expired"): break
    time.sleep(2)
print("2) status:", j["status"], "studies:", j.get("study_count"), "bytes:", j.get("package_bytes"))
if j["status"] != "ready":
    print("   FAIL:", j.get("error")); sys.exit(1)

dtok, key = j["download_token"], j["package_key"]

# 3) mrn 불일치 토큰 거부
st, _ = req("GET", f"{BASE}/api/v1/patient-export/requests/{rid}", tok("WRONG-MRN"))
print("3) mrn 불일치 조회 (403 기대):", st)

# 4) 수령 (게이트웨이)
st, pkg = req("GET", f"{GATEWAY}/portal-export/{dtok}")
print("4) download:", st, "len:", len(pkg))

# 5) 재다운로드 거부 (410 기대)
st2, _ = req("GET", f"{GATEWAY}/portal-export/{dtok}")
print("5) 재다운로드 (410 기대):", st2)

# 6) 복호 + manifest
plain = Fernet(key.encode()).decrypt(pkg)
zf = zipfile.ZipFile(io.BytesIO(plain))
names = zf.namelist()
mani = json.loads(zf.read("manifest.json"))
print("6) 복호 OK. 파일:", len(names), "studies:", len(mani["studies"]), "보고서포함:", sum(1 for s in mani["studies"] if s["has_report"]))
print("   샘플:", names[:4])
