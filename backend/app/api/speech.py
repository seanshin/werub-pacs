"""Speech-to-text API for radiology dictation.

Supports:
1. Browser Web Speech API (handled client-side, no backend needed)
2. Whisper API endpoint (for higher accuracy Korean medical dictation)
"""
import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from app.core.security import get_current_user, RequireRole
from app.models.user import Role, User
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/speech", tags=["음성 인식"])


@router.post("/transcribe", summary="음성 → 텍스트 변환 (Whisper)")
async def transcribe_audio(
    file: UploadFile = File(..., description="오디오 파일 (wav, mp3, webm)"),
    language: str = Query("ko", description="언어 코드 (ko, en)"),
    user: User = Depends(RequireRole(Role.RADIOLOGIST, Role.ADMIN)),
):
    """오디오 파일을 텍스트로 변환합니다.

    Whisper 모델을 사용하여 높은 정확도의 한국어 음성 인식을 제공합니다.
    브라우저 Web Speech API보다 의학 용어 인식에 우수합니다.

    지원 포맷: WAV, MP3, WebM, OGG
    최대 파일 크기: 25MB
    """
    data = await file.read()

    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "파일이 너무 큽니다 (최대 25MB)")

    # Try local Whisper first (if installed)
    try:
        import whisper
        model = whisper.load_model("base")

        # Save to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        result = model.transcribe(tmp_path, language=language)

        import os
        os.unlink(tmp_path)

        return {
            "text": result["text"],
            "language": result.get("language", language),
            "segments": [
                {"start": s["start"], "end": s["end"], "text": s["text"]}
                for s in result.get("segments", [])
            ],
            "engine": "whisper-local",
        }

    except ImportError:
        logger.info("Whisper not installed locally, trying Ollama...")

    # Fallback: Try Ollama with audio-capable model
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            # Use Ollama if available
            resp = await client.get("http://localhost:11434/api/tags")
            if resp.status_code == 200:
                # Ollama doesn't natively support audio transcription
                # Return guidance to use browser API
                pass
    except Exception:
        pass

    # Final fallback
    return {
        "text": "",
        "engine": "none",
        "message": "Whisper 모델이 설치되지 않았습니다. 브라우저 음성 인식(🎤 버튼)을 사용하세요. "
                   "Whisper 설치: pip install openai-whisper",
    }


@router.get("/status", summary="음성 인식 엔진 상태")
async def speech_status(user: User = Depends(RequireRole(Role.RADIOLOGIST, Role.ADMIN))):
    """사용 가능한 음성 인식 엔진을 확인합니다."""
    engines = {
        "browser_web_speech_api": {
            "available": True,
            "description": "Chrome/Edge 내장 음성 인식 (한국어 지원)",
            "accuracy": "중간",
            "latency": "실시간",
        },
    }

    # Check Whisper
    try:
        import whisper
        engines["whisper_local"] = {
            "available": True,
            "description": f"OpenAI Whisper (로컬)",
            "accuracy": "높음",
            "latency": "배치",
        }
    except ImportError:
        engines["whisper_local"] = {
            "available": False,
            "install": "pip install openai-whisper",
        }

    return {"engines": engines}
