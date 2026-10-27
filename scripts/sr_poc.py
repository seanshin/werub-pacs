"""SR PoC for sr-streaming (3d-ai-performance Track B gate).

Fetches rendered CT/MR slices from production WADO-RS, simulates the
progressive-streaming path (downscale x0.5 = the "lowres first" payload),
then upscales back with bicubic / FSRCNN / EDSR and scores SSIM+PSNR
against the original. Latency measured on CPU (Apple Silicon); the gate's
100ms target is for the RTX 5080 — CPU numbers are an upper bound.
"""
import io
import json
import time

import cv2
import httpx
import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim
from skimage.metrics import peak_signal_noise_ratio as psnr

BASE = "https://his.example.org"
N_PER_STUDY = 2  # slices sampled per study (middle-ish)

client = httpx.Client(base_url=BASE, timeout=60.0, verify=True)


def qido(path):
    r = client.get(f"/dicom-web{path}", headers={"Accept": "application/dicom+json"})
    return r.json() if r.status_code == 200 else []


def tag(item, t, default=""):
    v = item.get(t, {}).get("Value")
    return v[0] if v else default


def collect_slices():
    """Yield (modality, study, series, instance) for CT/MR studies."""
    out = []
    for s in qido("/studies?limit=50&includefield=00080061"):
        mods = s.get("00080061", {}).get("Value", [])
        mod = next((m for m in mods if m in ("CT", "MR")), None)
        if not mod:
            continue
        study_uid = tag(s, "0020000D")
        series_list = qido(f"/studies/{study_uid}/series")
        # largest series = the 3D stack
        series_list.sort(key=lambda x: int(tag(x, "00201209", 0) or 0), reverse=True)
        if not series_list:
            continue
        series_uid = tag(series_list[0], "0020000E")
        insts = qido(f"/studies/{study_uid}/series/{series_uid}/instances")
        if not insts:
            continue
        # middle slices
        mid = len(insts) // 2
        picks = insts[mid : mid + N_PER_STUDY]
        for inst in picks:
            out.append((mod, study_uid, series_uid, tag(inst, "00080018")))
    return out


def fetch_rendered(study, series, inst):
    r = client.get(
        f"/dicom-web/studies/{study}/series/{series}/instances/{inst}/rendered",
        headers={"Accept": "image/jpeg"},
    )
    if r.status_code != 200:
        return None
    img = Image.open(io.BytesIO(r.content)).convert("L")
    return np.array(img)


def make_sr(name, path):
    m = cv2.dnn_superres.DnnSuperResImpl_create()
    m.readModel(path)
    m.setModel(name, 2)
    return m


def upscale_dnn(model, lowres):
    bgr = cv2.cvtColor(lowres, cv2.COLOR_GRAY2BGR)
    t0 = time.perf_counter()
    up = model.upsample(bgr)
    dt = (time.perf_counter() - t0) * 1000
    return cv2.cvtColor(up, cv2.COLOR_BGR2GRAY), dt


def main():
    slices = collect_slices()
    print(f"collected {len(slices)} slices from CT/MR studies")

    fsrcnn = make_sr("fsrcnn", "/tmp/sr-poc/models/FSRCNN_x2.pb")
    edsr = make_sr("edsr", "/tmp/sr-poc/models/EDSR_x2.pb")

    rows = []
    for mod, study, series, inst in slices:
        orig = fetch_rendered(study, series, inst)
        if orig is None or min(orig.shape) < 128:
            continue
        # even dims for clean x2 round-trip
        h, w = orig.shape[0] // 2 * 2, orig.shape[1] // 2 * 2
        orig = orig[:h, :w]
        low = cv2.resize(orig, (w // 2, h // 2), interpolation=cv2.INTER_AREA)

        t0 = time.perf_counter()
        bic = cv2.resize(low, (w, h), interpolation=cv2.INTER_CUBIC)
        t_bic = (time.perf_counter() - t0) * 1000

        fs, t_fs = upscale_dnn(fsrcnn, low)
        ed, t_ed = upscale_dnn(edsr, low)

        row = {
            "modality": mod,
            "size": f"{w}x{h}",
            "ssim_bicubic": round(ssim(orig, bic), 4),
            "ssim_fsrcnn": round(ssim(orig, fs), 4),
            "ssim_edsr": round(ssim(orig, ed), 4),
            "psnr_bicubic": round(psnr(orig, bic), 2),
            "psnr_fsrcnn": round(psnr(orig, fs), 2),
            "psnr_edsr": round(psnr(orig, ed), 2),
            "ms_bicubic": round(t_bic, 1),
            "ms_fsrcnn": round(t_fs, 1),
            "ms_edsr": round(t_ed, 1),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    if not rows:
        print("NO DATA")
        return

    def avg(k):
        return round(sum(r[k] for r in rows) / len(rows), 4)

    print("\n=== SUMMARY (n=%d) ===" % len(rows))
    for k in ["ssim_bicubic", "ssim_fsrcnn", "ssim_edsr",
              "psnr_bicubic", "psnr_fsrcnn", "psnr_edsr",
              "ms_bicubic", "ms_fsrcnn", "ms_edsr"]:
        print(f"{k}: {avg(k)}")
    json.dump(rows, open("/tmp/sr-poc/results.json", "w"), indent=2)


if __name__ == "__main__":
    main()
