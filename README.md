# RobotLLMInteraction
Dieses Repository ermöglicht die dynamische Steuerung eines Roboters (UR3e) per Sprachbefehl. Nutzer können über Sprachsteuerung flexibel und intuitiv verschiedene Befehle an den Roboter übermitteln, um dessen Verhalten in Echtzeit zu steuern.

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