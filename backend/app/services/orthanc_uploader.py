"""Orthanc uploader service for DICOM instances.

Uploads DICOM instances (SEG, SR, etc.) to Orthanc via DICOMweb API.
Handles authentication, retries, and error recovery.

Features:
- Basic auth with Orthanc credentials
- Retry logic for transient failures
- Progress tracking
- Orthanc instance ID extraction
"""
import logging
from typing import Optional, Tuple
import asyncio
import httpx

from pydicom.dataset import FileDataset

logger = logging.getLogger(__name__)

# DICOMweb endpoint
DICOMWEB_BASE = "http://127.0.0.1:8042/dicom-web"

# Upload retry settings
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


class OrthancUploader:
    """Service for uploading DICOM instances to Orthanc."""

    def __init__(
        self,
        orthanc_url: str = DICOMWEB_BASE,
        username: str | None = None,
        password: str | None = None,
    ):
        from app.core.config import settings
        if username is None:
            username = settings.orthanc_username
        if password is None:
            password = settings.orthanc_password
        self.orthanc_url = orthanc_url
        self.username = username
        self.password = password
        self.logger = logger

    async def upload_dicom_instance(
        self,
        dicom_ds: FileDataset,
        instance_type: str = "SEG",
    ) -> str:
        """Upload a DICOM instance to Orthanc via DICOMweb.

        Args:
            dicom_ds: FileDataset to upload
            instance_type: Type of instance (SEG, SR, SC, ANN) for logging

        Returns:
            str: Orthanc instance ID

        Raises:
            Exception: If upload fails after retries
        """
        retry_count = 0
        last_error = None

        while retry_count < MAX_RETRIES:
            try:
                self.logger.info(
                    f"Uploading {instance_type} to Orthanc",
                    extra={
                        "attempt": retry_count + 1,
                        "max_retries": MAX_RETRIES,
                        "study_uid": getattr(dicom_ds, "StudyInstanceUID", "unknown"),
                    },
                )

                # Step 1: Save DICOM to binary
                dicom_bytes = self._serialize_dicom(dicom_ds)

                # Step 2: Upload via DICOMweb POST /studies
                orthanc_id = await self._post_dicomweb(dicom_bytes, instance_type)

                self.logger.info(
                    f"{instance_type} uploaded successfully",
                    extra={
                        "orthanc_id": orthanc_id,
                        "study_uid": getattr(dicom_ds, "StudyInstanceUID", "unknown"),
                    },
                )

                return orthanc_id

            except Exception as e:
                last_error = e
                retry_count += 1

                if retry_count < MAX_RETRIES:
                    self.logger.warning(
                        f"Upload attempt {retry_count} failed, retrying in {RETRY_DELAY}s",
                        extra={"error": str(e), "next_attempt": retry_count + 1},
                    )
                    await asyncio.sleep(RETRY_DELAY)
                else:
                    self.logger.error(
                        f"Upload failed after {MAX_RETRIES} retries",
                        extra={"error": str(e)},
                        exc_info=True,
                    )

        raise Exception(f"Failed to upload {instance_type} after {MAX_RETRIES} attempts: {str(last_error)}")

    async def _post_dicomweb(self, dicom_bytes: bytes, instance_type: str) -> str:
        """POST DICOM binary to DICOMweb /studies endpoint.

        Args:
            dicom_bytes: Serialized DICOM data
            instance_type: Instance type for logging

        Returns:
            str: Orthanc instance ID extracted from response headers

        Raises:
            Exception: If POST fails
        """
        url = f"{self.orthanc_url}/studies"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Step 1: POST with basic auth
                response = await client.post(
                    url,
                    content=dicom_bytes,
                    headers={"Content-Type": "application/dicom"},
                    auth=(self.username, self.password),
                )

                # Step 2: Check response status
                if response.status_code not in [200, 201]:
                    raise Exception(
                        f"DICOMweb POST failed with status {response.status_code}: {response.text}"
                    )

                # Step 3: Extract Orthanc instance ID from response
                # Orthanc returns Location header or JSON with IDs
                orthanc_id = self._extract_orthanc_id(response)

                self.logger.debug(
                    f"DICOMweb POST successful",
                    extra={"status": response.status_code, "orthanc_id": orthanc_id},
                )

                return orthanc_id

        except httpx.RequestError as e:
            self.logger.error(f"DICOMweb POST network error: {str(e)}", exc_info=True)
            raise

        except Exception as e:
            self.logger.error(f"DICOMweb POST error: {str(e)}", exc_info=True)
            raise

    def _serialize_dicom(self, dicom_ds: FileDataset) -> bytes:
        """Serialize DICOM dataset to binary format.

        Args:
            dicom_ds: FileDataset to serialize

        Returns:
            bytes: DICOM binary data

        Raises:
            Exception: If serialization fails
        """
        try:
            # Use pydicom's native serialization
            # Save to BytesIO and read back
            from io import BytesIO

            bio = BytesIO()
            dicom_ds.save_as(bio, write_like_original=False)
            return bio.getvalue()

        except Exception as e:
            self.logger.error(f"Failed to serialize DICOM: {str(e)}", exc_info=True)
            raise

    def _extract_orthanc_id(self, response: httpx.Response) -> str:
        """Extract Orthanc instance ID from HTTP response.

        Args:
            response: httpx.Response from DICOMweb POST

        Returns:
            str: Orthanc instance ID (e.g., "a1b2c3d4-e5f6...")

        Raises:
            Exception: If ID cannot be extracted
        """
        try:
            # Method 1: Check Location header
            if "Location" in response.headers:
                location = response.headers["Location"]
                # Location format: /dicom-web/studies/.../series/.../instances/{id}
                parts = location.split("/")
                if parts:
                    return parts[-1]

            # Method 2: Parse JSON response
            try:
                json_response = response.json()
                if "InstanceID" in json_response:
                    return json_response["InstanceID"]
                if "id" in json_response:
                    return json_response["id"]
            except Exception:
                pass

            # Method 3: Use Orthanc REST API to query uploaded instance
            # This is a fallback; normally the response should contain the ID
            raise Exception("Could not extract Orthanc instance ID from response")

        except Exception as e:
            self.logger.error(f"Failed to extract Orthanc ID: {str(e)}")
            raise

    async def verify_instance_in_orthanc(self, orthanc_id: str) -> bool:
        """Verify that an instance exists in Orthanc.

        Args:
            orthanc_id: Orthanc instance ID

        Returns:
            bool: True if instance exists, False otherwise
        """
        try:
            url = f"{self.orthanc_url}/instances/{orthanc_id}/metadata"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    auth=(self.username, self.password),
                )

                if response.status_code == 200:
                    self.logger.debug(f"Instance {orthanc_id} verified in Orthanc")
                    return True
                else:
                    self.logger.warning(f"Instance {orthanc_id} not found in Orthanc")
                    return False

        except Exception as e:
            self.logger.error(f"Error verifying instance: {str(e)}", exc_info=True)
            return False

    async def get_instance_metadata(self, orthanc_id: str) -> dict:
        """Retrieve instance metadata from Orthanc.

        Args:
            orthanc_id: Orthanc instance ID

        Returns:
            dict: Instance metadata (StudyUID, SeriesUID, etc.)

        Raises:
            Exception: If metadata retrieval fails
        """
        try:
            url = f"{self.orthanc_url}/instances/{orthanc_id}/metadata"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    auth=(self.username, self.password),
                )

                if response.status_code == 200:
                    metadata = response.json()
                    self.logger.debug(f"Retrieved metadata for instance {orthanc_id}")
                    return metadata
                else:
                    raise Exception(f"Failed to get metadata: {response.status_code}")

        except Exception as e:
            self.logger.error(f"Error retrieving metadata: {str(e)}", exc_info=True)
            raise
