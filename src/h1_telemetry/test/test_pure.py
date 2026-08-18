# Import smoke test: every pure module is importable WITHOUT ROS.
# Per-module behavioural tests live in test_*.py next to this file.
from h1_telemetry import anomaly, body_state, ring_buffer, thresholds, writer


def test_modules_importable_without_ros():
    assert ring_buffer.RateCounter
    assert ring_buffer.RingBuffer
    assert body_state.quaternion_to_pitch_roll_deg
    assert body_state.fall_risk_score
    assert thresholds.ThresholdEvaluator
    assert anomaly.AnomalyScorer
    assert writer.SampleWriter
