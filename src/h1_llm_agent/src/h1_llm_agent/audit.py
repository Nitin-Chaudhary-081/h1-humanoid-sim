"""JSONL audit log for agent turns (pure logic, no ROS imports).

One JSON line per event/turn, appended to a configurable path
(default /home/ubuntu/humanoid_sim_ws/data/llm_audit.jsonl).
Record schema: {ts, input_text, intent, tool_calls[], results[],
estop_active, outcome} — outcome is SUCCESS|FAILED|BLOCKED|TIMEOUT.
"""
import datetime
import json
from pathlib import Path

DEFAULT_AUDIT_PATH = '/home/ubuntu/humanoid_sim_ws/data/llm_audit.jsonl'


def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class AuditWriter:
    """Appends one JSON object per line. Creates parent directories."""

    def __init__(self, path=DEFAULT_AUDIT_PATH, clock=None):
        self.path = str(path)
        self._clock = clock if clock is not None else _utc_now_iso

    def write(self, record):
        """Append a record. `ts` is auto-stamped when absent."""
        record = dict(record)
        record.setdefault('ts', self._clock())
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record) + '\n')

    def read_records(self):
        """Read back all records (used by tests / offline tooling)."""
        path = Path(self.path)
        if not path.exists():
            return []
        records = []
        with path.open('r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
