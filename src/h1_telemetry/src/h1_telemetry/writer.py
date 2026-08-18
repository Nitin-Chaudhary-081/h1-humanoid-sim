"""CSV + JSONL sample writer.

Pure logic, no ROS imports. Appends one row to data/telemetry.csv and one
line to data/telemetry.jsonl per sample. Column set is fixed from the
first sample (header written exactly once, even across restarts).
"""

import csv
import json
import os

CSV_FILENAME = 'telemetry.csv'
JSONL_FILENAME = 'telemetry.jsonl'


class SampleWriter:
    """Append telemetry samples as CSV row + JSONL line.

    Args:
        data_dir: directory for the files (created if missing).
        csv_path / jsonl_path: optional explicit overrides.
        sample_keys: ordered column names for the CSV header. If None,
            the keys of the first sample are used.
    """

    def __init__(self, data_dir, csv_path=None, jsonl_path=None,
                 sample_keys=None):
        self.data_dir = data_dir
        self.csv_path = csv_path or os.path.join(data_dir, CSV_FILENAME)
        self.jsonl_path = jsonl_path or os.path.join(data_dir, JSONL_FILENAME)
        self._keys = list(sample_keys) if sample_keys is not None else None
        os.makedirs(data_dir, exist_ok=True)

    @property
    def keys(self):
        return list(self._keys) if self._keys is not None else None

    def write(self, sample):
        """Append one sample (mapping). Returns the keys in use.

        The CSV header is written only when the file is missing or empty
        (no header dupes across appends/restarts). JSONL has no header.
        """
        if self._keys is None:
            self._keys = list(sample.keys())
        keys = self._keys

        csv_exists = os.path.isfile(self.csv_path)
        need_header = not csv_exists or os.path.getsize(self.csv_path) == 0
        with open(self.csv_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
            if need_header:
                writer.writeheader()
            writer.writerow(sample)

        with open(self.jsonl_path, 'a') as f:
            f.write(json.dumps(sample, default=str) + '\n')

        return list(keys)
