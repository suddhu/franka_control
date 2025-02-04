import torch, glob, time, yaml
import numpy as np
import torchcontrol as toco
from typing import Dict
from polymetis import RobotInterface

HZ = 30
HOMES = {
    "pour": [0.1828, -0.4909, -0.0093, -2.4412, 0.2554, 3.3310, 0.5905],
    "scoop": [0.1828, -0.4909, -0.0093, -2.4412, 0.2554, 3.3310, 0.5905],
    "zip": [-0.1337, 0.3634, -0.1395, -2.3153, 0.1478, 2.7733, -1.1784],
    "circle": [-0.1337, 0.3634, -0.1395, -2.3153, 0.1478, 2.7733, -1.1784], # isdf mapping of room
    "scan": 
    # [-2.5170, -0.4619, -0.1252, -2.0640, -0.0952,  1.7888, -0.8808], # isdf mapping of tabletop (need to adjust workspace limits in polymetis nuc)
    [-0.2765, -0.6705,  0.1542, -2.5442,  0.1547,  2.2101, -1.0348], # front
    "insertion": [0.1828, -0.4909, -0.0093, -2.4412, 0.2554, 3.3310, 0.5905],
}
KQ_GAINS = {
    "record": [1, 1, 1, 1, 1, 1, 1],
    "default": [26.6667, 40.0000, 33.3333, 33.3333, 23.3333, 16.6667, 6.6667],
    "stiff": [240.0, 360.0, 300.0, 300.0, 210.0, 150.0, 60.0],
}
KQD_GAINS = {
    "record": [1, 1, 1, 1, 1, 1, 1],
    "default": [3.3333, 3.3333, 3.3333, 3.3333, 1.6667, 1.6667, 1.6667],
    "stiff": [30.0, 30.0, 30.0, 30.0, 15.0, 15.0, 15.0],
}
LOW_JOINTS = np.array([-2.8973, -1.7628, -2.8973, -3.0718, -2.8973, -0.0175, -2.8973])
HIGH_JOINTS = np.array([2.8973, 1.7628, 2.8973, -0.0698, 2.8973, 3.7525, 2.8973])


class PDControl(toco.PolicyModule):
    """
    Performs PD control around a desired joint position
    """

    def __init__(self, joint_pos_current, kq, kqd, **kwargs):
        """
        Args:
            joint_pos_current (torch.Tensor):   Joint positions at initialization
            kq, kqd (torch.Tensor):             PD gains (1d array)
        """
        super().__init__(**kwargs)
        self.q_desired = torch.nn.Parameter(joint_pos_current)
        self.feedback = toco.modules.JointSpacePD(kq, kqd)

    def forward(self, state_dict: Dict[str, torch.Tensor]):
        # Parse states
        q_current = state_dict["joint_positions"]
        qd_current = state_dict["joint_velocities"]

        # Execute PD control
        output = self.feedback(
            q_current, qd_current, self.q_desired, torch.zeros_like(qd_current)
        )
        return {"joint_torques": output}


class Rate:
    """
    Maintains constant control rate for POMDP loop
    """

    def __init__(self, frequency):
        self._period = 1.0 / frequency
        self._last = time.time()

    def sleep(self):
        current_delta = time.time() - self._last
        sleep_time = max(0, self._period - current_delta)
        if sleep_time:
            time.sleep(sleep_time)
        self._last = time.time()


def robot_setup(home_pos, gain_type, franka_ip="172.16.0.1"):
    # Initialize robot interface and reset
    robot = RobotInterface(ip_address=franka_ip, enforce_version=False)
    robot.set_home_pose(torch.Tensor(home_pos))
    print(f"Current joint state: {robot.get_joint_positions()}")    # get current joint state 
    robot.go_home()

    # Create and send PD Controller to Franka
    q_initial = robot.get_joint_positions()
    kq = torch.Tensor(KQ_GAINS[gain_type])
    kqd = torch.Tensor(KQD_GAINS[gain_type])
    pd_control = PDControl(joint_pos_current=q_initial, kq=kq, kqd=kqd)
    robot.send_torch_policy(pd_control, blocking=False)
    return robot, pd_control
