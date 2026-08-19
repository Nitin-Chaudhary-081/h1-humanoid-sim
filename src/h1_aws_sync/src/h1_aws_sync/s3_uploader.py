"""S3 JSONL uploader with a local byte-offset watermark.

Pure logic, no ROS. boto3 is imported lazily; tests inject a fake client.

The telemetry file is append-only JSONL. The watermark stores the byte
offset of the first not-yet-uploaded byte, so each line is uploaded
exactly once. A final line without a trailing newline (concurrent append
or interrupted write) is treated as in-progress and skipped until it is
completed.
"""

import json
import os
import time
from datetime import datetime, timezone

S3_WATERMARK_FILENAME = 'aws_sync_watermark'


class S3Uploader:

    def __init__(self, bucket, prefix='telemetry', region='ap-south-1',
                 telemetry_path=None, watermark_path=None, client=None,
                 content_type='application/x-ndjson', now_fn=None):
        self.bucket = bucket
        self.prefix = prefix.strip('/')
        self.region = region
        self.telemetry_path = telemetry_path
        self.watermark_path = watermark_path or os.path.join(
            os.path.dirname(telemetry_path or '.') or '.', S3_WATERMARK_FILENAME)
        self.content_type = content_type
        self.now_fn = now_fn or time.time
        if client is None:
            client = self._make_client()
        self.client = client

    def _make_client(self):
        import boto3
        return boto3.client('s3', region_name=self.region)

    def read_watermark(self):
        if not self.watermark_path or not os.path.isfile(self.watermark_path):
            return 0
        try:
            with open(self.watermark_path) as f:
                return max(0, int(f.read().strip() or 0))
        except (ValueError, OSError):
            return 0

    def write_watermark(self, offset):
        tmp = self.watermark_path + '.tmp'
        with open(tmp, 'w') as f:
            f.write(str(offset))
        os.replace(tmp, self.watermark_path)

    def _pending_lines(self):
        """Return (start_offset, raw_bytes) for complete lines after watermark.

        Returns [] for a missing or empty file. A file truncated below the
        watermark (rotation) resets the watermark to 0 and re-reads all.
        """
        if not self.telemetry_path or not os.path.isfile(self.telemetry_path):
            return [], 0
        size = os.path.getsize(self.telemetry_path)
        offset = self.read_watermark()
        if offset > size:
            offset = 0
        lines = []
        with open(self.telemetry_path, 'rb') as f:
            f.seek(offset)
            while True:
                start = f.tell()
                raw = f.readline()
                if not raw:
                    break
                if not raw.endswith(b'\n'):
                    break
                lines.append((start, raw))
        new_offset = lines[-1][0] + len(lines[-1][1]) if lines else offset
        return lines, new_offset

    def build_key(self, unix_ts):
        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        return '{prefix}/{y:04d}/{m:02d}/{d:02d}/telemetry-{ts}.jsonl'.format(
            prefix=self.prefix, y=dt.year, m=dt.month, d=dt.day, ts=int(unix_ts))

    def sync(self, dry_run=False):
        """Upload new lines to S3 and advance the watermark.

        Returns a dict: uploaded (count), key (str or None), offset (new
        watermark byte offset), samples (parsed dicts of uploaded lines).
        In dry_run mode nothing is uploaded and the watermark is untouched.
        """
        lines, new_offset = self._pending_lines()
        if not lines:
            return {'uploaded': 0, 'key': None,
                    'offset': self.read_watermark(), 'samples': []}
        body = b''.join(raw for _, raw in lines)
        key = self.build_key(self.now_fn())
        samples = []
        for _, raw in lines:
            try:
                samples.append(json.loads(raw.decode('utf-8')))
            except (ValueError, UnicodeDecodeError):
                continue
        if not dry_run:
            put_kwargs = {
                'Bucket': self.bucket,
                'Key': key,
                'Body': body,
            }
            if self.content_type:
                put_kwargs['ContentType'] = self.content_type
            self.client.put_object(**put_kwargs)
            self.write_watermark(new_offset)
        return {'uploaded': len(lines), 'key': key,
                'offset': new_offset, 'samples': samples}