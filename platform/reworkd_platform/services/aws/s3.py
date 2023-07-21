from typing import Dict

from boto3 import client as boto3_client
from pydantic import BaseModel

REGION = "us-east-1"


class PresignedPost(BaseModel):
    url: str
    fields: Dict[str, str]


class SimpleStorageService:
    def __init__(
        self,
    ) -> None:
        self._client = boto3_client("s3", region_name=REGION)

    def upload_url(
        self,
        bucket_name: str,
        object_name: str,
    ) -> PresignedPost:
        return PresignedPost(
            **self._client.generate_presigned_post(
                Bucket=bucket_name,
                Key=object_name,
            )
        )
