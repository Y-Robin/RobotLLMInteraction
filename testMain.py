# main.py
from gripper_control import gripper_open, gripper_close
from robot_teaching import teach_positions
from moveFun import send_pose_to_robot
import time
from stopRobot import stop_robot

# Erfasse z. B. 3 Posen vom Benutzer per Freedrive
positionen = teach_positions(num_positions=2)

# Weiterverarbeitung
print("Erfasste Positionen:")
for i, pose in enumerate(positionen):
    print(f"Pose {i+1}: {pose}")

# Fahre jede Pose 1x an
for _ in range(1):
    for i, pose in enumerate(positionen):
        print(f"Fahre zu Pose {i+1}...")
        send_pose_to_robot(pose,acceleration=0.8,velocity=1.2)
        print("Ziel erreicht")
        #time.sleep(2)  # Optional: kurze Pause zwischen Bewegungen



print("Öffne Greifer...")
gripper_open()

time.sleep(2)

print("Schließe Greifer...")
gripper_close()

stop_robot()