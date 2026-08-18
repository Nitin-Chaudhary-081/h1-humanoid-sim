# Periodic telemetry sample published by h1_telemetry
builtin_interfaces/Time stamp
float32 cpu_load            # 0..1 fraction of one CPU
float32 ram_used_mb
float32 joint_states_hz
float32 odometry_hz
float32 imu_hz
float32 body_pitch_deg
float32 body_roll_deg
float32 fall_risk_score     # 0..1
float32 anomaly_score       # 0..1 (IsolationForest / thresholds)
bool anomaly
string detail
