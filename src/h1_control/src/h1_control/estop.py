"""Pure estop gate logic (no ROS imports).

Decision function used by the control server: given the latched /estop
boolean and the current mode/status, decide whether joint commands may be
published and whether an active goal must be aborted.
"""


class EstopGate:
    """Gate for command publication and goal aborts.

    - allows(estop_active): whether cmd_pos may be published at all.
    - should_abort(estop_active, running): whether a RUNNING goal must be
      terminated (True when estop latches while a motion goal is active).
    """

    @staticmethod
    def allows(estop_active):
        return not bool(estop_active)

    @staticmethod
    def should_abort(estop_active, running):
        return bool(estop_active) and bool(running)
