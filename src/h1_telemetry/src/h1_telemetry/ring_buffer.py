"""Fixed-size ring buffer + rate counter.

Pure logic, no ROS imports (unit-testable).

RateCounter computes the publication rate (Hz) of a topic from a window
of message stamps (seconds, e.g. msg.header.stamp.sec + nanosec * 1e-9).
"""

from collections import deque


class RingBuffer:
    """Fixed-capacity sliding window of numeric values."""

    def __init__(self, capacity=100):
        if capacity < 1:
            raise ValueError('capacity must be >= 1')
        self.capacity = capacity
        self._buf = deque(maxlen=capacity)

    def append(self, value):
        self._buf.append(value)

    def __len__(self):
        return len(self._buf)

    def __iter__(self):
        return iter(self._buf)

    def clear(self):
        self._buf.clear()

    @property
    def values(self):
        """List of current values in insertion order (oldest first)."""
        return list(self._buf)

    @property
    def oldest(self):
        return self._buf[0] if self._buf else None

    @property
    def newest(self):
        return self._buf[-1] if self._buf else None

    @property
    def full(self):
        return len(self._buf) == self.capacity


class RateCounter:
    """Compute Hz of a topic from a window of message stamps (seconds)."""

    def __init__(self, window_size=100):
        if window_size < 2:
            raise ValueError('window_size must be >= 2')
        self._window = RingBuffer(capacity=window_size)

    def add_stamp(self, stamp_sec):
        """Record one message stamp. Non-monotonic stamps are still kept,
        but they degrade the window estimate (caller should pass source
        time, which in sim is monotonic per topic)."""
        self._window.append(float(stamp_sec))

    def add_msg(self, header_stamp):
        """Convenience: pass a header with sec/nanosec int fields
        (e.g. sensor_msgs/Header or builtin_interfaces/Time-like object)."""
        self.add_stamp(header_stamp.sec + header_stamp.nanosec * 1e-9)

    def hz(self):
        """Rate in Hz over the window. 0.0 when < 2 samples or span <= 0."""
        vals = self._window.values
        if len(vals) < 2:
            return 0.0
        span = vals[-1] - vals[0]
        if span <= 0.0:
            return 0.0
        return (len(vals) - 1) / span

    def clear(self):
        self._window.clear()

    @property
    def count(self):
        return len(self._window)
