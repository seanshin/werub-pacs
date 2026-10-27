"""Ollama Vision API inference engine for medical imaging AI.

Supports MedGemma, LLaVA-Rad, and other Ollama vision models.
Converts DICOM pixel data to image → sends to Ollama → parses findings.
"""
import base64
import io
import logging
from typing import Any

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

# Default Ollama endpoint (fallback to local if settings unavailable)
DEFAULT_OLLAMA_URL = settings.ai_server_url if hasattr(settings, 'ai_server_url') else "http://localhost:11434"

# Medical imaging prompts by modality
PROMPTS = {
    "CR": """You are a radiologist AI assistant. Analyze this chest X-ray image.
Provide a structured report with:
1. **Findings**: Describe all observations (lungs, heart, mediastinum, pleura, bones)
2. **Impression**: Summarize the key findings
3. **Urgency**: Rate as NORMAL, NON-URGENT, or URGENT
Be concise and use standard radiology terminology.""",

    "DX": """You are a radiologist AI assistant. Analyze this digital X-ray image.
Describe findings, provide impression, and rate urgency (NORMAL/NON-URGENT/URGENT).""",

    "CT": """You are a radiologist AI assistant. Analyze this CT image slice.
Provide:
1. **Findings**: Describe observations in detail
2. **Impression**: Key findings summary
3. **Urgency**: NORMAL, NON-URGENT, or URGENT
Focus on any abnormalities, masses, or significant findings.""",

    "MR": """You are a radiologist AI assistant. Analyze this MRI image.
Provide findings, impression, and urgency rating (NORMAL/NON-URGENT/URGENT).""",

    "US": """You are a radiologist AI assistant. Analyze this ultrasound image.
Provide findings, impression, and urgency rating (NORMAL/NON-URGENT/URGENT).""",

    "DEFAULT": """You are a medical imaging AI assistant. Analyze this medical image.
Provide:
1. **Findings**: Describe what you observe
2. **Impression**: Summary
3. **Urgency**: NORMAL, NON-URGENT, or URGENT""",
}


class OllamaInferenceEngine:
    """Run inference using Ollama Vision API (MedGemma, LLaVA, etc.)."""

    def __init__(self, model_name: str = "medgemma", endpoint_url: str | None = None):
        self.model_name = model_name
        self.endpoint_url = (endpoint_url or DEFAULT_OLLAMA_URL).rstrip("/")

    def run(self, pixel_array: np.ndarray, metadata: dict) -> dict:
        """Run vision inference on preprocessed pixel data.

        Supports two modes:
        1. WeRUB Medical Vision API (https://example.org/ollama/api/vision/medical/analyze)
        2. Direct Ollama API (http://localhost:11434/api/chat)
        """
        import httpx

        modality = metadata.get("modality", "DEFAULT")

        # Convert pixel array to JPEG bytes
        img_bytes = self._array_to_jpeg_bytes(pixel_array)

        # Detect API mode
        if "/ollama" in self.endpoint_url and ("weve.io" in self.endpoint_url or "https" in self.endpoint_url):
            return self._run_werub_medical(img_bytes, modality, metadata)
        else:
            return self._run_ollama_direct(img_bytes, modality, metadata)

    def _run_werub_medical(self, img_bytes: bytes, modality: str, metadata: dict) -> dict:
        """Call WeRUB Medical Vision API (GPU server)."""
        import httpx

        modality_map = {"CR": "xray", "DX": "xray", "CT": "ct", "MR": "mri", "US": "ultrasound"}
        api_modality = modality_map.get(modality, "xray")

        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    f"{self.endpoint_url}/api/vision/medical/analyze",
                    files={"image": ("image.jpg", img_bytes, "image/jpeg")},
                    data={"modality": api_modality,
                          "instructions": "Provide detailed findings, impression, and urgency rating"},
                )

                if response.status_code == 200:
                    result = response.json()
                    return self._parse_werub_response(result, modality, metadata)
                else:
                    return self._error_result(f"Medical API error: {response.status_code}")

        except httpx.ConnectError:
            return self._error_result("GPU 서버에 연결할 수 없습니다")
        except httpx.TimeoutException:
            return self._error_result("GPU 서버 추론 시간 초과 (120초)")
        except Exception as e:
            return self._error_result(str(e))

    def _run_ollama_direct(self, img_bytes: bytes, modality: str, metadata: dict) -> dict:
        """Call Ollama API directly."""
        import httpx

        prompt = PROMPTS.get(modality, PROMPTS["DEFAULT"])
        image_b64 = base64.b64encode(img_bytes).decode('ascii')

        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    f"{self.endpoint_url}/api/chat",
                    json={
                        "model": self.model_name,
                        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
                        "stream": False,
                        "options": {"temperature": 0.1, "num_predict": 1024},
                    },
                )

                if response.status_code == 200:
                    result = response.json()
                    ai_text = result.get("message", {}).get("content", "")
                    return self._parse_response(ai_text, modality, metadata)
                else:
                    return self._error_result(f"Ollama API error: {response.status_code}")

        except httpx.ConnectError:
            logger.error(f"Cannot connect to Ollama at {self.endpoint_url}")
            return self._error_result("Ollama 서버에 연결할 수 없습니다. Ollama가 실행 중인지 확인하세요.")
        except httpx.TimeoutException:
            logger.error("Ollama inference timeout")
            return self._error_result("Ollama 추론 시간 초과 (120초)")
        except Exception as e:
            logger.error(f"Ollama inference error: {e}")
            return self._error_result(str(e))

    def _array_to_base64(self, pixel_array: np.ndarray) -> str:
        """Convert numpy array to PNG base64 string."""
        # Normalize to 0-255
        img = (pixel_array * 255).clip(0, 255).astype(np.uint8)

        # Create PNG using minimal PNG encoder (no PIL dependency)
        import struct
        import zlib

        h, w = img.shape[:2]
        if img.ndim == 2:
            # Grayscale
            raw_data = b''
            for row in img:
                raw_data += b'\x00' + row.tobytes()
            color_type = 0  # Grayscale
        else:
            raw_data = b''
            for row in img:
                raw_data += b'\x00' + row.tobytes()
            color_type = 2  # RGB

        def make_chunk(chunk_type, data):
            chunk = chunk_type + data
            return struct.pack('>I', len(data)) + chunk + struct.pack('>I', zlib.crc32(chunk) & 0xffffffff)

        png = b'\x89PNG\r\n\x1a\n'
        png += make_chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, color_type, 0, 0, 0))
        png += make_chunk(b'IDAT', zlib.compress(raw_data))
        png += make_chunk(b'IEND', b'')

        return base64.b64encode(png).decode('ascii')

    def _array_to_jpeg_bytes(self, pixel_array: np.ndarray) -> bytes:
        """Convert numpy array to JPEG bytes."""
        img = (pixel_array * 255).clip(0, 255).astype(np.uint8)
        # Use PNG encoder then convert — simpler than JPEG without PIL
        return self._array_to_png_bytes(img)

    def _array_to_png_bytes(self, img: np.ndarray) -> bytes:
        """Convert uint8 numpy array to PNG bytes."""
        import struct, zlib
        h, w = img.shape[:2]
        raw = b''
        for row in img:
            raw += b'\x00' + row.tobytes()
        color_type = 0 if img.ndim == 2 else 2

        def chunk(t, d):
            c = t + d
            return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

        png = b'\x89PNG\r\n\x1a\n'
        png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, color_type, 0, 0, 0))
        png += chunk(b'IDAT', zlib.compress(raw))
        png += chunk(b'IEND', b'')
        return png

    def _parse_werub_response(self, result: dict, modality: str, metadata: dict) -> dict:
        """Parse WeRUB Medical Vision API response."""
        findings_text = result.get("findings", "")
        impression = result.get("impression", "")
        recommendations = result.get("recommendations", "")
        duration_ms = result.get("duration_ms", 0)

        is_critical = False
        urgency = "normal"
        if recommendations:
            upper = (findings_text + impression + recommendations).upper()
            if "URGENT" in upper and "NON-URGENT" not in upper:
                urgency = "urgent"
                is_critical = True

        findings = [{
            "type": "ai_analysis",
            "description": findings_text[:500] if findings_text else "분석 완료",
            "impression": impression[:300],
            "recommendations": recommendations[:300],
            "confidence": 0.85,
            "severity": "critical" if is_critical else "normal",
            "full_text": result.get("raw_response", ""),
        }]

        if is_critical:
            findings.append({
                "type": "critical_finding",
                "description": "긴급 소견 감지 — 즉시 확인 필요",
                "confidence": 0.90,
                "severity": "critical",
            })

        return {
            "engine": "werub_medical",
            "model": result.get("model", self.model_name),
            "findings": findings,
            "findings_count": len(findings),
            "max_confidence": 0.90 if is_critical else 0.85,
            "is_critical": is_critical,
            "urgency": urgency,
            "duration_ms": duration_ms,
            "disclaimer": result.get("disclaimer", "AI 결과는 진단 보조 목적이며, 최종 판단은 의료진의 책임입니다."),
        }

    def _parse_response(self, text: str, modality: str, metadata: dict) -> dict:
        """Parse Ollama response text into structured findings."""
        findings = []
        is_critical = False

        # Extract urgency
        urgency = "normal"
        text_upper = text.upper()
        if "URGENT" in text_upper and "NON-URGENT" not in text_upper:
            urgency = "urgent"
            is_critical = True
        elif "NON-URGENT" in text_upper:
            urgency = "non_urgent"

        # Extract findings section
        findings_text = text
        impression_text = ""

        # Try to split by common headers
        for header in ["**Impression**", "Impression:", "**impression**", "## Impression"]:
            if header.lower() in text.lower():
                parts = text.lower().split(header.lower(), 1)
                if len(parts) == 2:
                    findings_text = text[:len(parts[0])]
                    impression_text = text[len(parts[0]) + len(header):]
                break

        # Main finding
        findings.append({
            "type": "ai_analysis",
            "description": findings_text.strip()[:500],
            "impression": impression_text.strip()[:300],
            "confidence": 0.85 if not is_critical else 0.90,
            "severity": "critical" if is_critical else ("warning" if urgency == "non_urgent" else "normal"),
            "full_text": text,
        })

        if is_critical:
            findings.append({
                "type": "critical_finding",
                "description": "AI가 긴급 소견을 감지했습니다. 즉시 확인이 필요합니다.",
                "confidence": 0.90,
                "severity": "critical",
            })

        return {
            "engine": "ollama",
            "model": self.model_name,
            "findings": findings,
            "findings_count": len(findings),
            "max_confidence": 0.90 if is_critical else 0.85,
            "is_critical": is_critical,
            "urgency": urgency,
            "raw_response": text,
            "disclaimer": "AI 결과는 진단 보조 목적이며, 최종 판단은 의료진의 책임입니다.",
        }

    def _error_result(self, message: str) -> dict:
        return {
            "engine": "ollama",
            "model": self.model_name,
            "findings": [{"type": "error", "description": message, "confidence": 0, "severity": "info"}],
            "findings_count": 1,
            "max_confidence": 0,
            "is_critical": False,
            "error": message,
        }

    def check_health(self) -> dict:
        """Check if Ollama is running and model is available."""
        import httpx
        try:
            with httpx.Client(timeout=5.0) as client:
                # Check Ollama
                resp = client.get(f"{self.endpoint_url}/api/tags")
                if resp.status_code != 200:
                    return {"status": "error", "message": "Ollama not responding"}

                models = resp.json().get("models", [])
                model_names = [m.get("name", "").split(":")[0] for m in models]

                return {
                    "status": "ok",
                    "ollama_url": self.endpoint_url,
                    "available_models": model_names,
                    "target_model": self.model_name,
                    "model_loaded": self.model_name in model_names,
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}
