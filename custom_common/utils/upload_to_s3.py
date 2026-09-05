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

def upload_file_to_s3(file_encoded: bytes, file_content_type: str, s3_key: str, S3_BUCKET_NAME: str, CLOUDFRONT_DOMAIN: Optional[str]) -> str:
    """
    Uploads a file byte stream to S3 and returns the public CloudFront URL.
    """
    response = {
        "error": False,
        "message": "Successfully uploaded file to S3",
        "data": {}
    }

    if not S3_BUCKET_NAME:
        logger.error("AWS S3/CloudFront settings are not configured properly.")
        response["error"] = True
        response["message"] = "AWS S3/CloudFront settings are not configured properly."
        return response

    try:
        # boto3 automatically uses the EC2 IAM Role if no credentials are provided
        s3_client = boto3.client("s3")

        logger.info("Uploading file to S3 | bucket=%s | key=%s", S3_BUCKET_NAME, s3_key)

        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=file_encoded,
            ContentType=file_content_type,
        )
        
        logger.info("Successfully uploaded file to S3 | bucket=%s | key=%s", S3_BUCKET_NAME, s3_key)
        
        if CLOUDFRONT_DOMAIN:
            cloudfront_url = f"{CLOUDFRONT_DOMAIN}/{s3_key}" 
            logger.info("Successfully uploaded file to S3 | url=%s", cloudfront_url)
            
            response["data"]["url"] = cloudfront_url
            
        return response
        
    except Exception as e:
        logger.exception("Failed to upload file to S3 | bucket=%s | key=%s | error=%s", S3_BUCKET_NAME, s3_key, e)
        response["error"] = True
        response["message"] = "Failed to upload file to S3"
        return response
    