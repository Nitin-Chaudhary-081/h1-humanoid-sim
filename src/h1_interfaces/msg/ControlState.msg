# Current state of the robot's motion controller (published by h1_control)
builtin_interfaces/Time stamp

int8 MODE_STAND = 0
int8 MODE_WALK  = 1
int8 MODE_STOP  = 2

int8 STATUS_IDLE      = 0
int8 STATUS_RUNNING   = 1
int8 STATUS_SUCCEEDED = 2
int8 STATUS_FAILED    = 3
int8 STATUS_ESTOPPED  = 4

int8 mode              # one of MODE_*
int8 status            # one of STATUS_*
float64 goal_distance  # meters; 0 unless mode == MODE_WALK
float64 distance_traveled
string detail
