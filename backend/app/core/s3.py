"""S3/MinIO client for file storage."""

import logging

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)


def get_s3_client():
    if not settings.s3_endpoint:
        return None

    # signature_version="s3v4": AWS regions created after 2014 and MinIO reject
    # presigned URLs signed with the legacy SigV2 algorithm.
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version="s3v4"),
    )


def upload_file(data: bytes, path: str, content_type: str) -> str | None:
    client = get_s3_client()
    if not client:
        logger.warning("S3 not configured, skipping upload")
        return None

    try:
        client.put_object(
            Bucket=settings.s3_bucket,
            Key=path,
            Body=data,
            ContentType=content_type,
        )
        return f"{settings.s3_endpoint}/{settings.s3_bucket}/{path}"
    except ClientError:
        logger.exception("S3 upload failed for %s", path)
        return None


def delete_file(path: str) -> bool:
    client = get_s3_client()
    if not client:
        return False

    try:
        client.delete_object(Bucket=settings.s3_bucket, Key=path)
        return True
    except ClientError:
        logger.exception("S3 delete failed for %s", path)
        return False


def get_presigned_url(
    path: str,
    expires_in: int = 3600,
    *,
    content_disposition: str | None = None,
) -> str | None:
    client = get_s3_client()
    if not client:
        return None

    params: dict = {"Bucket": settings.s3_bucket, "Key": path}
    if content_disposition:
        params["ResponseContentDisposition"] = content_disposition

    try:
        return client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )
    except ClientError:
        logger.exception("S3 presigned URL failed for %s", path)
        return None


# ---------------------------------------------------------------------------
# Multipart upload (R3a) — large media files (audio/video) up to 500 MB.
# Frontend uploads each part directly to S3 via presigned URLs.
# ---------------------------------------------------------------------------

DEFAULT_PART_SIZE = 8 * 1024 * 1024  # 8 MB
MAX_OBJECT_BYTES = 500 * 1024 * 1024  # 500 MB (FR-10)


def init_multipart_upload(path: str, content_type: str) -> str | None:
    client = get_s3_client()
    if not client:
        return None

    try:
        response = client.create_multipart_upload(
            Bucket=settings.s3_bucket,
            Key=path,
            ContentType=content_type,
        )
        return response["UploadId"]
    except ClientError:
        logger.exception("S3 multipart init failed for %s", path)
        return None


def get_part_presigned_url(
    path: str,
    upload_id: str,
    part_number: int,
    expires_in: int = 3600,
) -> str | None:
    client = get_s3_client()
    if not client:
        return None

    try:
        return client.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": settings.s3_bucket,
                "Key": path,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expires_in,
        )
    except ClientError:
        logger.exception(
            "S3 multipart part-url failed for %s part=%s", path, part_number
        )
        return None


def complete_multipart_upload(
    path: str,
    upload_id: str,
    parts: list[dict],
) -> str | None:
    """Finalize a multipart upload.

    ``parts`` is a list of ``{"PartNumber": int, "ETag": str}`` dicts in
    ascending part order.
    """

    client = get_s3_client()
    if not client:
        return None

    try:
        sorted_parts = sorted(parts, key=lambda p: p["PartNumber"])
        client.complete_multipart_upload(
            Bucket=settings.s3_bucket,
            Key=path,
            UploadId=upload_id,
            MultipartUpload={"Parts": sorted_parts},
        )
        return f"{settings.s3_endpoint}/{settings.s3_bucket}/{path}"
    except ClientError:
        logger.exception("S3 multipart complete failed for %s", path)
        return None


def abort_multipart_upload(path: str, upload_id: str) -> bool:
    client = get_s3_client()
    if not client:
        return False

    try:
        client.abort_multipart_upload(
            Bucket=settings.s3_bucket,
            Key=path,
            UploadId=upload_id,
        )
        return True
    except ClientError:
        logger.exception("S3 multipart abort failed for %s", path)
        return False


def head_object(path: str) -> dict | None:
    client = get_s3_client()
    if not client:
        return None

    try:
        return client.head_object(Bucket=settings.s3_bucket, Key=path)
    except ClientError:
        logger.exception("S3 head_object failed for %s", path)
        return None


def download_bytes(path: str) -> bytes | None:
    """Read a file's bytes from S3/MinIO. Returns ``None`` if storage is
    not configured or the object is missing — callers must treat ``None``
    as "no content available" instead of raising.
    """
    client = get_s3_client()
    if not client:
        return None
    try:
        response = client.get_object(Bucket=settings.s3_bucket, Key=path)
        return response["Body"].read()
    except ClientError:
        logger.exception("S3 get_object failed for %s", path)
        return None
