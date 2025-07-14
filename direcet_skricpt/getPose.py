import socket

robot_ip = "192.168.25.3"  # IP des Roboters
robot_port = 30002          # Port zum Senden von URScript

ur_script = """
def send_pose():
  socket_open("192.168.25.2", 30003)
  pose = get_actual_tcp_pose()
  socket_send_string(to_str(pose))
  socket_close()
end
send_pose()
"""

#ur_script = b"def send_pose():\n" \
#            b"  socket_open(\"192.168.25.2\", 30003)\n" \
#            b"  pose = get_actual_tcp_pose()\n" \
#            b"  socket_send_string(to_str(pose))\n" \
#            b"  socket_close()\n" \
#            b"end\n" \
#            b"send_pose()\n"


#ur_script = b"def send_pose():\n" \
#            b"  socket_open(\"192.168.25.2\", 30003)\n" \
#            b"  socket_send_string(\"Test\")\n" \
#            b"  socket_close()\n" \
#            b"end\n" \
#            b"send_pose()\n"


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((robot_ip, robot_port))
    s.sendall(ur_script.encode())
    print(ur_script)
