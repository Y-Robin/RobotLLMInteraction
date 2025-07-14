# main.py
from robot_teaching import teach_positions
from moveFun import send_pose_to_robot
import time

# Erfasse z. B. 3 Posen vom Benutzer per Freedrive
positionen = teach_positions(num_positions=3)

# Weiterverarbeitung
print("Erfasste Positionen:")
for i, pose in enumerate(positionen):
    print(f"Pose {i+1}: {pose}")

# Fahre jede Pose 2x an
for _ in range(2):
    for i, pose in enumerate(positionen):
        print(f"Fahre zu Pose {i+1}...")
        send_pose_to_robot(pose)
        print("Ziel erreicht")
        #time.sleep(2)  # Optional: kurze Pause zwischen Bewegungen
