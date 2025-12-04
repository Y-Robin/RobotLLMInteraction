# RobotLLMInteraction
Dieses Repository ermöglicht die dynamische Steuerung eines Roboters (UR3e) per Sprachbefehl. Nutzer können über Sprachsteuerung flexibel und intuitiv verschiedene Befehle an den Roboter übermitteln, um dessen Verhalten in Echtzeit zu steuern.
Die GUI kann mithilfe von llmRobot_withSys_GUI.py gestartet werden. Das Systemprompt kann über die demo2.txt angepasst werden. Es wird ein API-Key für Open-AI benötigt welcher in .env gespeichert werden muss.

# Python Version
- Python 3.11.9

# VENV
- Erstelle eine venv und installiere die Notwendigen Bibliotheken
- dotenv, openai, sounddevice scipy und keyboard
- Passe die ip des Roboters und des PC an(Roboter: 192.168.25.3, PC: 192.168.25.2)
- Ports sind aus der Anleitung übernommens

# Aktiviere venv:
- Falls noch nicht geschehen: ```Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser ```
- Aktivieren mittels ```.venv\scripts\activate ```

# Beispiele für die Steuerung (Pick and place)
- Öffne den Gripper
- Lerne 4 neue Positionen
- Fahre zu Position 2, öffne den Gripper, fahre zu Position 1, schließe den Gripper, fahren dann zu den Position 2, 3, 4 und öffne dann den Greifer und gehe dann zu den Positionen 3 und 2
- Greife bitte das Werkstück, bringe es zum Förderband 2 und lasse es los. Aktiviere das Förderband, bis das Werkstück am Ende angekommen ist, deaktiviere das Förderband und dann nehme das Werkstück von Position 3 und bringe es zum Endpunkt.
