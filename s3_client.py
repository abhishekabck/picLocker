"""boto3 client against PersonalS3's S3-compatible endpoint (SigV4)."""

import logging

import boto3
from botocore.config import Config

import config

log = logging.getLogger("piclocker.s3")

_client = None


def get_s3():
    """Lazy singleton — built once, reused everywhere."""
    global _client
    if _client is None:
        log.info("creating S3 client endpoint=%s bucket=%s", config.PS3_HOST, config.PS3_BUCKET)
        _client = boto3.client(
            "s3",
            endpoint_url=config.PS3_HOST,
            aws_access_key_id=config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
            # PersonalS3 (like most non-AWS S3 servers) rejects the
            # aws-chunked checksum trailer botocore>=1.36 sends by default.
            config=Config(
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
    return _client
