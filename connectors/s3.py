"""S3 helper - import and use anywhere.

    from connectors.s3 import s3

    # --- server-side ---
    key  = s3.upload_file("/tmp/x.csv")     # -> "uploads/<id>-x.csv"
    data = s3.download(key)                  # bytes  (accepts key, s3://, or https URL)
    path = s3.download_to_tmp(link)          # -> local temp path

    # --- direct browser upload (file bytes never touch the backend) ---
    info = s3.presign_put("report.pdf")      # -> {key, upload_url, get_url, bucket}
    #   browser:  PUT the file  ->  info["upload_url"]
    #   browser:  send info["key"] back to the backend
    bucket, key = s3.parse(link)             # accept a key, s3://..., or https S3 URL

Requires S3_BUCKET, AWS creds, and AWS_REGION in the environment.
"""
import os
import uuid
import tempfile
import mimetypes
from urllib.parse import urlparse, unquote

import boto3
from botocore.config import Config as BotoConfig

from core.config import cfg


class S3:
    """Thin, reusable wrapper around an S3 bucket. One shared instance: `s3`."""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:                       # lazy: no AWS call at import
            # Force SigV4 + regional virtual-hosted addressing so presigned URLs
            # point at the bucket's region (s3.<region>.amazonaws.com). Without
            # this, boto3 can emit a legacy SigV2 global URL and S3 answers 307.
            self._client = boto3.client(
                "s3", region_name=cfg.region,
                config=BotoConfig(signature_version="s3v4",
                                  s3={"addressing_style": "virtual"}))
        return self._client

    @property
    def bucket(self):
        if not cfg.s3_bucket:
            raise RuntimeError("S3_BUCKET is not set - add it to your .env")
        return cfg.s3_bucket

    # ---------------- keys / links ----------------
    def new_key(self, filename, prefix="uploads"):
        """A collision-resistant object key that preserves the original name."""
        safe = os.path.basename(filename or "file").replace(" ", "_")
        return f"{prefix}/{uuid.uuid4().hex[:12]}-{safe}"

    def parse(self, link):
        """Accept a bare key, an `s3://bucket/key` URL, or an https S3 URL and
        return (bucket, key)."""
        if not link:
            raise ValueError("empty s3 link")
        if "://" not in link:
            return self.bucket, link.lstrip("/")
        u = urlparse(link)
        if u.scheme == "s3":
            return u.netloc, u.path.lstrip("/")
        host, path = u.netloc, unquote(u.path.lstrip("/"))
        if host.startswith(("s3.", "s3-")):            # path-style: s3.region.../bucket/key
            bkt, _, key = path.partition("/")
            return bkt, key
        return host.split(".s3")[0], path              # virtual-hosted: bucket.s3.../key

    # ---------------- upload ----------------
    def upload_bytes(self, data, key=None, content_type=None, filename=None):
        key = key or self.new_key(filename or "file")
        ct = content_type or mimetypes.guess_type(key)[0]
        extra = {"ContentType": ct} if ct else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        return key

    def upload_file(self, path, key=None):
        key = key or self.new_key(os.path.basename(path))
        ct = mimetypes.guess_type(path)[0]
        self.client.upload_file(path, self.bucket, key,
                                ExtraArgs={"ContentType": ct} if ct else None)
        return key

    # ---------------- download ----------------
    def download(self, link):
        bkt, key = self.parse(link)
        return self.client.get_object(Bucket=bkt, Key=key)["Body"].read()

    def download_to_tmp(self, link):
        bkt, key = self.parse(link)
        fd, path = tempfile.mkstemp(suffix=os.path.splitext(key)[1])
        os.close(fd)
        self.client.download_file(bkt, key, path)
        return path

    # ---------------- presigned URLs ----------------
    def presign_put(self, filename, content_type=None, expires=3600, prefix="uploads"):
        """URL the browser can PUT a file to directly. Returns the new key plus
        a matching presigned GET url so the object can be read back."""
        key = self.new_key(filename, prefix)
        params = {"Bucket": self.bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        url = self.client.generate_presigned_url("put_object", Params=params,
                                                 ExpiresIn=expires)
        return {"key": key, "upload_url": url, "bucket": self.bucket,
                "get_url": self.presign_get(key, expires)}

    def presign_get(self, link, expires=3600):
        bkt, key = self.parse(link)
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": bkt, "Key": key}, ExpiresIn=expires)


s3 = S3()
