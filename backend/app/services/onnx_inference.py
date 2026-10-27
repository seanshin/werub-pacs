"""ONNX Runtime inference engine.

Supports real ONNX model files for medical image analysis.
Falls back to statistical analysis if no model file is available.
"""
import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

# Try to import onnxruntime
try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
    logger.info(f"ONNX Runtime {ort.__version__} available")
except ImportError:
    ONNX_AVAILABLE = False
    logger.warning("ONNX Runtime not available — using statistical analysis fallback")


class OnnxInferenceEngine:
    """Run inference using ONNX model or statistical fallback."""

    def __init__(self, model_path: str | None = None, checksum_sha256: str | None = None):
        self.session = None
        self.model_path = model_path

        # 무결성 검증 (INV-NET-02): 등록된 sha256과 파일 해시 대조 — 불일치 시
        # 로드 거부(통계 폴백으로 진행되지 않도록 명시적 예외).
        if model_path and checksum_sha256 and os.path.exists(model_path):
            import hashlib
            h = hashlib.sha256()
            with open(model_path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            actual = h.hexdigest()
            if actual.lower() != checksum_sha256.strip().lower():
                raise ValueError(
                    f"model checksum mismatch: {model_path} "
                    f"expected={checksum_sha256[:12]}… actual={actual[:12]}…")

        if model_path and os.path.exists(model_path) and ONNX_AVAILABLE:
            try:
                self.session = ort.InferenceSession(model_path)
                inputs = self.session.get_inputs()
                outputs = self.session.get_outputs()
                logger.info(f"Loaded ONNX model: {model_path}")
                logger.info(f"  Inputs: {[(i.name, i.shape) for i in inputs]}")
                logger.info(f"  Outputs: {[(o.name, o.shape) for o in outputs]}")
            except Exception as e:
                logger.error(f"Failed to load ONNX model: {e}")
                self.session = None

    def run(self, pixel_array: np.ndarray, metadata: dict) -> dict:
        """Run inference on preprocessed pixel data.

        Args:
            pixel_array: normalized float32 array (0-1), shape (H, W) or (H, W, C)
            metadata: dict with modality, rows, columns, pixel_spacing

        Returns:
            dict with findings, confidence, etc.
        """
        if self.session:
            return self._run_onnx(pixel_array, metadata)
        return self._run_statistical(pixel_array, metadata)

    def _run_onnx(self, pixel_array: np.ndarray, metadata: dict) -> dict:
        """Run actual ONNX model inference."""
        input_info = self.session.get_inputs()[0]
        input_name = input_info.name
        input_shape = input_info.shape  # e.g., [1, 1, 224, 224]

        # Reshape input to match model expectations
        img = pixel_array.astype(np.float32)
        target_h = input_shape[2] if len(input_shape) == 4 else img.shape[0]
        target_w = input_shape[3] if len(input_shape) == 4 else img.shape[1]

        # Simple resize using numpy (no cv2 dependency)
        if img.shape[0] != target_h or img.shape[1] != target_w:
            indices_h = np.linspace(0, img.shape[0] - 1, target_h).astype(int)
            indices_w = np.linspace(0, img.shape[1] - 1, target_w).astype(int)
            img = img[np.ix_(indices_h, indices_w)]

        # Reshape to NCHW
        if len(input_shape) == 4:
            channels = input_shape[1]
            if channels == 1:
                img = img.reshape(1, 1, target_h, target_w)
            elif channels == 3:
                img = np.stack([img] * 3).reshape(1, 3, target_h, target_w)
        else:
            img = img.reshape(1, -1)

        # Run inference
        outputs = self.session.run(None, {input_name: img})
        output = outputs[0]

        # Interpret output (classification model)
        if output.ndim == 2 and output.shape[1] >= 2:
            # Binary classification: [normal_prob, abnormal_prob]
            probs = self._softmax(output[0])
            abnormal_prob = float(probs[1]) if len(probs) > 1 else float(probs[0])
            normal_prob = float(probs[0])

            findings = []
            is_critical = False

            if abnormal_prob > 0.5:
                severity = "critical" if abnormal_prob > 0.8 else "warning"
                is_critical = abnormal_prob > 0.8
                findings.append({
                    "type": "abnormality_detected",
                    "description": f"AI model detected potential abnormality (confidence: {abnormal_prob:.1%})",
                    "confidence": round(abnormal_prob, 3),
                    "severity": severity,
                    "model_output": output[0].tolist(),
                })
            else:
                findings.append({
                    "type": "normal",
                    "description": f"No significant abnormalities detected (confidence: {normal_prob:.1%})",
                    "confidence": round(normal_prob, 3),
                    "severity": "normal",
                })

            return {
                "engine": "onnx",
                "findings": findings,
                "findings_count": len(findings),
                "max_confidence": round(max(abnormal_prob, normal_prob), 3),
                "is_critical": is_critical,
                "probabilities": {"normal": round(normal_prob, 3), "abnormal": round(abnormal_prob, 3)},
            }
        else:
            # Raw output
            return {
                "engine": "onnx",
                "findings": [{"type": "raw_output", "description": "Model output", "output": output.tolist()}],
                "findings_count": 1,
                "max_confidence": 0.5,
                "is_critical": False,
            }

    def _run_statistical(self, pixel_array: np.ndarray, metadata: dict) -> dict:
        """Statistical analysis fallback when no ONNX model is available."""
        modality = metadata.get("modality", "")
        mean_val = float(pixel_array.mean())
        std_val = float(pixel_array.std())
        p5, p95 = float(np.percentile(pixel_array, 5)), float(np.percentile(pixel_array, 95))
        dynamic_range = p95 - p5

        findings = []
        is_critical = False
        max_confidence = 0.0

        # Modality-specific analysis
        if modality in ("CT", "CR", "DX"):
            # High contrast regions may indicate abnormality
            if std_val > 0.3:
                confidence = min(0.85, std_val * 1.2)
                max_confidence = max(max_confidence, confidence)
                findings.append({
                    "type": "high_contrast_region",
                    "description": f"High contrast variation detected (σ={std_val:.3f})",
                    "confidence": round(confidence, 3),
                    "severity": "warning",
                })

            if mean_val > 0.7:
                confidence = 0.75
                max_confidence = max(max_confidence, confidence)
                is_critical = True
                findings.append({
                    "type": "high_density",
                    "description": "Unusually high density region — requires review",
                    "confidence": confidence,
                    "severity": "critical",
                })

        elif modality == "MR":
            if dynamic_range < 0.3:
                confidence = 0.6
                max_confidence = max(max_confidence, confidence)
                findings.append({
                    "type": "low_contrast",
                    "description": f"Low contrast detected (range={dynamic_range:.3f})",
                    "confidence": confidence,
                    "severity": "info",
                })

        if not findings:
            max_confidence = 0.90
            findings.append({
                "type": "normal",
                "description": "No significant abnormalities detected",
                "confidence": 0.90,
                "severity": "normal",
            })

        return {
            "engine": "statistical",
            "findings": findings,
            "findings_count": len(findings),
            "max_confidence": round(max_confidence, 3),
            "is_critical": is_critical,
            "image_stats": {
                "mean": round(mean_val, 4),
                "std": round(std_val, 4),
                "p5": round(p5, 4),
                "p95": round(p95, 4),
                "dynamic_range": round(dynamic_range, 4),
            },
            "disclaimer": "AI 결과는 진단 보조 목적이며, 최종 판단은 의료진의 책임입니다.",
        }

    @staticmethod
    def _softmax(x):
        e_x = np.exp(x - np.max(x))
        return e_x / e_x.sum()
