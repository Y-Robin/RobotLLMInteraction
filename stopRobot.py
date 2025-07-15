import socket
def stop_robot(robot_ip = "192.168.25.3",robot_port = 30002):

    ur_script = """
def stopRobot():
  textmsg("Stop!!")
end
stopRobot()
"""


    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((robot_ip, robot_port))
        s.sendall(ur_script.encode())
        print(ur_script)
