from gripper_control import gripper_open, gripper_close

def main():
    print("Öffne Greifer...")
    gripper_open()

    # ggf. Wartezeit einfügen
    import time
    time.sleep(2)

    print("Schließe Greifer...")
    gripper_close()

if __name__ == "__main__":
    main()
