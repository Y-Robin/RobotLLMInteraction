import socket

robot_ip = "192.168.25.3"  # IP deines Roboters
robot_port = 30002         # Steuerport

ur_script = """
def move_to_position():
  movel(p[0.2, 0.1, 0.3, 0, 3.14, 0], a=1.2, v=0.25)
end
move_to_position()
"""

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((robot_ip, robot_port))
    s.sendall(ur_script.encode('ascii'))
    s.recv(1024)  # Dummy-Read