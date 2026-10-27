"""Standard application exceptions for OpenPACS.

All exceptions produce a unified error response format:

    {
        "error": {
            "code": "ERROR_CODE",
            "message": "Human-readable message",
            "details": { ... }
        },
        "request_id": "uuid-1234",
        "timestamp": "2026-05-13T10:30:00Z"
    }
"""
from typing import Any, Dict, Optional
from uuid import uuid4


class AppException(Exception):
    """Base application exception. All custom exceptions inherit from this."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.request_id = str(uuid4())  # ← v1.1: Added request_id
        super().__init__(message)


# ── Authentication / Authorization ─────────────────────────────────────────


class AuthenticationError(AppException):
    """Token missing, invalid, or revoked."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(code="INVALID_CREDENTIALS", message=message, status_code=401)


class TokenRevokedError(AppException):
    """Token has been explicitly revoked (blacklisted on logout)."""

    def __init__(self):
        super().__init__(
            code="TOKEN_EXPIRED",
            message="Token has been revoked. Please log in again.",
            status_code=401,
        )


class PermissionDeniedError(AppException):
    """Authenticated user lacks required role."""

    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(code="INSUFFICIENT_PERMISSIONS", message=message, status_code=403)


# ── DICOM / Validation ─────────────────────────────────────────────────────


class DicomValidationError(AppException):
    """Non-standard or malformed DICOM data detected."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="DICOM_VALIDATION_ERROR",
            message=message,
            status_code=422,
            details=details,
        )


class DicomUploadError(AppException):
    """DICOM upload to Orthanc failed."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="DICOM_UPLOAD_ERROR",
            message=message,
            status_code=502,
            details=details,
        )


class DicomNormalizationError(AppException):
    """DICOM normalization pipeline error."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="DICOM_NORMALIZATION_ERROR",
            message=message,
            status_code=400,
            details=details,
        )


class NormalizationFailedError(DicomNormalizationError):
    """Auto-correction could not be applied to the DICOM dataset."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        # Call AppException directly so we can set our own error_code
        AppException.__init__(
            self,
            code="NORMALIZATION_FAILED",
            message=message,
            status_code=400,
            details=details or {},
        )


class RevalidationFailedError(DicomNormalizationError):
    """Post-normalization re-validation still fails — reject the upload."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        AppException.__init__(
            self,
            code="REVALIDATION_FAILED",
            message=message,
            status_code=422,
            details=details or {},
        )


# ── Resource ───────────────────────────────────────────────────────────────


class NotFoundError(AppException):
    """Requested resource does not exist."""

    def __init__(self, resource: str, resource_id: str = ""):
        msg = f"{resource} not found"
        if resource_id:
            msg = f"{resource} '{resource_id}' not found"
        super().__init__(code="RESOURCE_NOT_FOUND", message=msg, status_code=404)


class ConflictError(AppException):
    """Resource already exists or state conflict."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="CONFLICT",
            message=message,
            status_code=409,
            details=details,
        )


# ── Service / Infrastructure ───────────────────────────────────────────────


class ValidationError(AppException):
    """Request payload failed validation."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            status_code=400,
            details=details,
        )


class ForbiddenError(AppException):
    """Authenticated user is not allowed to perform this action."""

    def __init__(self, message: str = "Forbidden"):
        super().__init__(code="FORBIDDEN", message=message, status_code=403)


class InternalServerError(AppException):
    """Unexpected server-side error."""

    def __init__(self, message: str = "Internal server error", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="INTERNAL_SERVER_ERROR",
            message=message,
            status_code=500,
            details=details,
        )


class OrthancError(AppException):
    """Downstream Orthanc server returned an unexpected response."""

    def __init__(self, message: str = "Orthanc server error", status_code: int = 502):
        super().__init__(code="ORTHANC_ERROR", message=message, status_code=status_code)


class AIInferenceError(AppException):
    """AI model inference failed."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="AI_INFERENCE_ERROR",
            message=message,
            status_code=500,
            details=details,
        )


# ── Phase 5: AI Integration ────────────────────────────────────────────────


class AIModelError(AppException):
    """Base class for AI model management errors."""

    def __init__(
        self,
        message: str,
        code: str = "AI_MODEL_ERROR",
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(code=code, message=message, status_code=status_code, details=details)


class InvalidONNXFormat(AIModelError):
    """ONNX model file is invalid or incompatible."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="INVALID_ONNX_FORMAT",
            message=message,
            status_code=422,
            details=details,
        )


class ModelAlreadyExists(AIModelError):
    """AI model with the same name and version already exists."""

    def __init__(self, name: str, version: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="MODEL_ALREADY_EXISTS",
            message=f"AI model '{name}' version '{version}' already exists",
            status_code=409,
            details=details,
        )


class InferenceJobError(AIModelError):
    """Base class for inference job errors."""

    def __init__(
        self,
        message: str,
        code: str = "INFERENCE_JOB_ERROR",
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(code=code, message=message, status_code=status_code, details=details)


class InferenceJobNotFoundError(InferenceJobError):
    """Inference job does not exist."""

    def __init__(self, job_id: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="INFERENCE_JOB_NOT_FOUND",
            message=f"Inference job '{job_id}' not found",
            status_code=404,
            details=details,
        )


class ModelNotAvailable(AIModelError):
    """AI model is not available (inactive, deleted, or missing)."""

    def __init__(self, model_id: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="MODEL_NOT_AVAILABLE",
            message=f"AI model '{model_id}' is not available",
            status_code=404,
            details=details,
        )


# ── Phase 4: Batch Normalization ───────────────────────────────────────────


class BatchJobError(AppException):
    """Base class for batch normalization job errors."""

    def __init__(
        self,
        message: str,
        code: str = "BATCH_JOB_ERROR",
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(code=code, message=message, status_code=status_code, details=details)


class BatchUploadError(BatchJobError):
    """Failed to accept or persist files during batch upload."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="BATCH_UPLOAD_ERROR",
            message=message,
            status_code=400,
            details=details,
        )


class BatchNormalizationError(BatchJobError):
    """A normalization step failed for one or more files in the batch."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="BATCH_NORMALIZATION_ERROR",
            message=message,
            status_code=422,
            details=details,
        )


class BatchProcessingError(BatchJobError):
    """Batch Celery task encountered an unrecoverable error."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="BATCH_PROCESSING_ERROR",
            message=message,
            status_code=500,
            details=details,
        )


class ZipExtractionError(BatchJobError):
    """ZIP archive extraction failed or contained no valid DICOM files."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="ZIP_EXTRACTION_ERROR",
            message=message,
            status_code=400,
            details=details,
        )


class DicomMagicByteError(BatchJobError):
    """File does not start with the DICOM magic bytes (DICM at offset 128)."""

    def __init__(self, filename: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="DICOM_MAGIC_BYTE_ERROR",
            message=f"File '{filename}' is not a valid DICOM file (missing DICM preamble)",
            status_code=422,
            details=details,
        )


class BatchFileValidationError(BatchJobError):
    """One or more files in the batch failed pre-upload validation."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="BATCH_FILE_VALIDATION_ERROR",
            message=message,
            status_code=422,
            details=details,
        )


class BatchQuotaError(BatchJobError):
    """Batch size or file count exceeds allowed quota."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="BATCH_QUOTA_EXCEEDED",
            message=message,
            status_code=429,
            details=details,
        )
