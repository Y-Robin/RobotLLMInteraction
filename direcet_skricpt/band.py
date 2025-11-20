import socket

robot_ip = "192.168.25.3"
robot_port = 30002

def send_urscript(script):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((robot_ip, robot_port))
        s.sendall(script.encode())
        print("----- URScript gesendet -----")
        print(script)
        print("------------------------------")

def start_band(band, direction, speed_volt=5):
    # IO-Zuweisungen pro Band
    if band == 1:
        std_do = 6
        config_do = 0
        analog_out = 0
    elif band == 2:
        std_do = 7
        config_do = 4
        analog_out = 1
    else:
        raise ValueError("Ungültiges Band (1 oder 2)!")

    # Richtung
    direction_bool = True if direction == "F" else False

    # 0–10 V → 0.0–1.0
    analog_value = speed_volt / 10.0

    ur_script = f"""
def start_conveyor():
  set_standard_analog_out({analog_out}, 0.0)
  set_standard_digital_out({std_do}, False)
  set_standard_digital_out({std_do}, True)
  set_configurable_digital_out({config_do}, {str(direction_bool)})
  sleep(0.05)
  set_standard_analog_out({analog_out}, {analog_value})

  textmsg("Band {band} gestartet, Richtung {'vorwaerts' if direction_bool else 'rueckwaerts'}")
end
start_conveyor()
"""
    send_urscript(ur_script)

def stop_band(band):
    if band == 1:
        std_do = 6
        analog_out = 0
    elif band == 2:
        std_do = 7
        analog_out = 1
    else:
        raise ValueError("Ungültiges Band (1 oder 2)!")

    ur_script = f"""
def stop_conveyor():
  set_standard_digital_out({std_do}, False)
  set_standard_analog_out({analog_out}, 0.0)
  textmsg("Band {band} gestoppt")
end
stop_conveyor()
"""
    send_urscript(ur_script)


# ----------------------------------------------
# Hauptmenü
# ----------------------------------------------

while True:
    print("\n--- Förderbandsteuerung ---")
    print("1 = Band starten")
    print("2 = Band stoppen")
    print("X = Beenden")
    choice = input("Auswahl: ").strip().upper()

    if choice == "1":
        band = int(input("Welches Band? (1/2): "))
        direction = input("Richtung (F=vorwärts, R=rückwärts): ").strip().upper()
        speed = float(input("Geschwindigkeit in Volt (0–10, Standard 5): ") or 5)
        start_band(band, direction, speed)

    elif choice == "2":
        band = int(input("Welches Band stoppen? (1/2): "))
        stop_band(band)

    elif choice == "X":
        break

    else:
        print("Ungültige Eingabe!")
