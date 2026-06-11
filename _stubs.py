from uuid import uuid4
# ConnectionError is a Python builtin — no import needed (and no dependency on requests)


class S3Stub:
    def __init__(self):
        self.offline = False

    def _check(self):
        if self.offline:
            raise ConnectionError("S3 offline (simulated)")

    def put_object(self, **kwargs):
        self._check()
        required_keys = ["Bucket", "Key", "Body", "ContentType"]
        if not all(key in kwargs for key in required_keys):
            raise Exception("Missing required keys in put_object")

    def create_multipart_upload(self, **kwargs):
        self._check()
        required_keys = ["Bucket", "Key", "ContentType"]
        if not all(key in kwargs for key in required_keys):
            raise Exception("Missing required keys in put_object")
        return {"UploadId": str(uuid4())}

    def upload_part(self, **kwargs):
        self._check()
        required_keys = ["Bucket", "Key", "Body", "UploadId", "PartNumber"]
        if not all(key in kwargs for key in required_keys):
            raise Exception("Missing required keys in put_object")
        return {"ETag": str(uuid4())}

    def complete_multipart_upload(self, **kwargs):
        self._check()
        required_keys = ["Bucket", "Key", "MultipartUpload", "UploadId"]
        if not all(key in kwargs for key in required_keys):
            raise Exception("Missing required keys in put_object")
        part_numbers = [part["PartNumber"] for part in kwargs["MultipartUpload"]["Parts"]]
        if part_numbers != sorted(part_numbers):
            raise Exception("Part numbers are out of order.")




def stub_embedding():
    import numpy as np
    return np.ones(512, dtype=np.float32)


