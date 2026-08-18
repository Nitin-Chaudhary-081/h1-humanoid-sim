# Unit tests for ring_buffer.py (pure, no ROS).
import pytest

from h1_telemetry.ring_buffer import RateCounter, RingBuffer


def test_ring_buffer_capacity_drops_oldest():
    buf = RingBuffer(capacity=3)
    for v in range(10):
        buf.append(v)
    assert len(buf) == 3
    assert buf.values == [7, 8, 9]
    assert buf.oldest == 7
    assert buf.newest == 9
    assert buf.full


def test_ring_buffer_clear():
    buf = RingBuffer(capacity=5)
    buf.append(1.0)
    buf.clear()
    assert len(buf) == 0
    assert buf.oldest is None
    assert buf.newest is None


def test_ring_buffer_invalid_capacity():
    with pytest.raises(ValueError):
        RingBuffer(capacity=0)


def test_rate_counter_known_hz():
    rc = RateCounter(window_size=100)
    dt = 0.1  # 10 Hz
    t = 100.0
    for _ in range(21):
        rc.add_stamp(t)
        t += dt
    assert rc.count == 21
    assert rc.hz() == pytest.approx(10.0, rel=0.01)


def test_rate_counter_window_limit():
    rc = RateCounter(window_size=10)
    for i in range(50):
        rc.add_stamp(float(i) * 0.1)
    assert rc.count == 10  # sliding window keeps last 10
    assert rc.hz() == pytest.approx(10.0, rel=0.01)


def test_rate_counter_high_rate():
    rc = RateCounter(window_size=100)
    t = 0.0
    for _ in range(200):
        rc.add_stamp(t)
        t += 0.005  # 200 Hz
    assert rc.hz() == pytest.approx(200.0, rel=0.01)


def test_rate_counter_empty_and_single():
    assert RateCounter().hz() == 0.0
    rc = RateCounter()
    rc.add_stamp(1.0)
    assert rc.hz() == 0.0


def test_rate_counter_duplicate_stamps_no_div0():
    rc = RateCounter()
    for _ in range(50):
        rc.add_stamp(123.0)
    assert rc.hz() == 0.0  # span == 0 -> guarded, no ZeroDivisionError


def test_rate_counter_add_msg_header_like():
    class Header:
        def __init__(self, sec, nanosec):
            self.sec = sec
            self.nanosec = nanosec

    rc = RateCounter()
    for i in range(11):
        rc.add_msg(Header(100 + i, 0))  # 1 Hz apart
    assert rc.hz() == pytest.approx(1.0, rel=0.01)


def test_rate_counter_clear():
    rc = RateCounter()
    rc.add_stamp(1.0)
    rc.add_stamp(2.0)
    rc.clear()
    assert rc.hz() == 0.0
