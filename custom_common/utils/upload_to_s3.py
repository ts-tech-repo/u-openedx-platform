"""
AWS S3 & CloudFront utilities for file management.
Relies on the EC2 Instance IAM Role for authentication (no hardcoded credentials).
"""

import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)


def upload_file_to_s3(
    file_encoded: bytes,
    file_content_type: str,
    s3_key: str,
    S3_BUCKET_NAME: str,
    CLOUDFRONT_DOMAIN: Optional[str],
) -> dict:
    """
    Uploads a file byte stream to S3 and returns the public CloudFront URL.

    Returns:
        {
            "error": bool,
            "message": str,
            "data": {
                "url": str
            }
        }
    """

    logger.info(
        "========== S3 UPLOAD START =========="
    )

    logger.info(
        "S3 upload request received | "
        "bucket=%s | key=%s | content_type=%s | file_size=%s bytes | "
        "cloudfront_configured=%s",
        S3_BUCKET_NAME,
        s3_key,
        file_content_type,
        len(file_encoded) if file_encoded else 0,
        bool(CLOUDFRONT_DOMAIN),
    )

    response = {
        "error": False,
        "message": "Successfully uploaded file to S3",
        "data": {},
    }

    # ------------------------------------------------------------------
    # Validate input
    # ------------------------------------------------------------------

    if not S3_BUCKET_NAME:
        logger.error(
            "S3 upload aborted | S3_BUCKET_NAME is empty or not configured"
        )

        response["error"] = True
        response["message"] = (
            "AWS S3/CloudFront settings are not configured properly."
        )

        logger.info("========== S3 UPLOAD END | FAILED ==========")

        return response

    if not file_encoded:
        logger.warning(
            "S3 upload received empty file | bucket=%s | key=%s",
            S3_BUCKET_NAME,
            s3_key,
        )

    if not s3_key:
        logger.error(
            "S3 upload aborted | s3_key is empty | bucket=%s",
            S3_BUCKET_NAME,
        )

        response["error"] = True
        response["message"] = "S3 file key is required."

        logger.info("========== S3 UPLOAD END | FAILED ==========")

        return response

    # ------------------------------------------------------------------
    # Create S3 client
    # ------------------------------------------------------------------

    try:
        logger.info(
            "Creating boto3 S3 client | authentication=IAM role/default AWS credential chain"
        )

        # boto3 automatically uses the EC2 IAM Role if no explicit
        # credentials are provided.
        s3_client = boto3.client("s3")

        logger.info(
            "Successfully created boto3 S3 client"
        )

        # ------------------------------------------------------------------
        # Upload file
        # ------------------------------------------------------------------

        logger.info(
            "Starting S3 put_object | bucket=%s | key=%s | "
            "content_type=%s | file_size=%s bytes",
            S3_BUCKET_NAME,
            s3_key,
            file_content_type,
            len(file_encoded),
        )

        upload_response = s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=file_encoded,
            ContentType=file_content_type,
        )

        logger.info(
            "S3 put_object completed successfully | "
            "bucket=%s | key=%s | etag=%s | version_id=%s | "
            "request_id=%s",
            S3_BUCKET_NAME,
            s3_key,
            upload_response.get("ETag"),
            upload_response.get("VersionId"),
            upload_response.get("ResponseMetadata", {}).get(
                "RequestId"
            ),
        )

        logger.info(
            "S3 response metadata | %s",
            upload_response.get("ResponseMetadata"),
        )

        # ------------------------------------------------------------------
        # Generate CloudFront URL
        # ------------------------------------------------------------------

        if CLOUDFRONT_DOMAIN:
            cloudfront_domain = CLOUDFRONT_DOMAIN.rstrip("/")

            cloudfront_url = (
                f"{cloudfront_domain}/{s3_key.lstrip('/')}"
            )

            logger.info(
                "CloudFront URL generated successfully | "
                "bucket=%s | key=%s | url=%s",
                S3_BUCKET_NAME,
                s3_key,
                cloudfront_url,
            )

            response["data"]["url"] = cloudfront_url

        else:
            logger.warning(
                "CloudFront domain is not configured | "
                "S3 upload succeeded but public URL was not generated | "
                "bucket=%s | key=%s",
                S3_BUCKET_NAME,
                s3_key,
            )

        logger.info(
            "S3 upload completed successfully | "
            "bucket=%s | key=%s | file_size=%s bytes | "
            "cloudfront_url_generated=%s",
            S3_BUCKET_NAME,
            s3_key,
            len(file_encoded),
            bool(CLOUDFRONT_DOMAIN),
        )

        logger.info(
            "========== S3 UPLOAD END | SUCCESS =========="
        )

        return response

    # ------------------------------------------------------------------
    # AWS-specific error
    # ------------------------------------------------------------------

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        error_message = e.response.get("Error", {}).get("Message")
        request_id = e.response.get("ResponseMetadata", {}).get(
            "RequestId"
        )

        logger.error(
            "AWS ClientError during S3 upload | "
            "bucket=%s | key=%s | error_code=%s | "
            "error_message=%s | request_id=%s",
            S3_BUCKET_NAME,
            s3_key,
            error_code,
            error_message,
            request_id,
            exc_info=True,
        )

        response["error"] = True
        response["message"] = (
            "Failed to upload file to S3"
        )

        logger.info(
            "========== S3 UPLOAD END | FAILED =========="
        )

        return response

    # ------------------------------------------------------------------
    # Unexpected error
    # ------------------------------------------------------------------

    except Exception as e:
        logger.exception(
            "Unexpected error during S3 upload | "
            "bucket=%s | key=%s | content_type=%s | "
            "file_size=%s bytes | error=%s",
            S3_BUCKET_NAME,
            s3_key,
            file_content_type,
            len(file_encoded) if file_encoded else 0,
            str(e),
        )

        response["error"] = True
        response["message"] = (
            "Failed to upload file to S3"
        )

        logger.info(
            "========== S3 UPLOAD END | FAILED =========="
        )

        return response
