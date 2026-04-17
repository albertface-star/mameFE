MAME_Frontend_Root/
│
├── mame.exe                # (Required) The MAME emulator executable
├── mame_frontend.py        # (Required) This Python script
│
├── roms/                   # (Required) Place your .zip / .7z ROMs here
│   ├── game1.zip
│   └── game2.zip
│
├── snap/                   # (Optional) Game screenshots (png)
│   ├── game1.png
│   └── game2.png
│
├── icons/                  # (Optional) Game icons (ico/png)
│   └── game1.ico
│
├── hiscore/                # (Auto-created) High score data
├── ini/                    # (Auto-created) Game configuration & Autosave states
│
├── game_list.json          # (Auto-created) ROM database
├── play_counts.json        # (Auto-created) Statistics
└── lists.json              # (Auto-created) Custom lists
A modern, lightweight, and PyQt6-based graphical frontend for MAME. It provides a clean user interface to manage, search, and launch your ROMs, featuring play count tracking, custom lists, and snapshot previews.

Python MAME Frontend ScreenshotPyQt6License
Features

    Fast ROM Management: Uses a cached game_list.json to avoid slow MAME XML parsing on every startup.
    Visual Preview: Displays game snapshots (snap) and icons (if available) with smooth fade animations.
    Play Counting: Tracks how many times you launch each game and sorts your list by popularity.
    Custom Lists: Create and manage custom game lists (e.g., "Favorites", "Platformers") to filter your collection.
    State Management: Toggle "Save Game on Exit" (Autosave) directly from the context menu.
    High DPI Support: Optimized for Windows with crisp text rendering on high-resolution screens.
    Themes: Switch between a native Dark Mode and a Light Mode.
    Search & Filter: Real-time filtering by name or ROM name.

Requirements

    Python 3.8+
    MAME: The executable must be named mame.exe and placed in the same folder as the script.
    Python Libraries:

    pip install PyQt6 Pillow

Installation

    Clone or Download this repository.
    Ensure your folder structure looks like this (the script will create missing folders automatically):

    /MAME_Frontend_Folder  ├── mame.exe            <-- Required  ├── mame_frontend.py    <-- This script  ├── roms/               <-- Place your .zip/.7z ROMs here  ├── snap/               <-- Place game screenshots here (romname.png)  ├── icons/              <-- Place game icons here (romname.ico/png)  ├── hiscore/            <-- Auto-generated  └── ini/                <-- Auto-generated

    Run the script:

    python mame_frontend.py

Usage
First Run

    Launch the application.
    Click the Refresh button if the game list is empty.
    The tool will scan your roms/ folder and generate a game_list.json file. This might take a moment depending on the size of your collection.

Controls

    Click: Select a game to see the snapshot.
    Double Click: Launch the game in MAME.
    Right Click: Open a context menu to:
        Reset play counts.
        Toggle Autosave (Save state on exit).
        Add/Remove the game from custom lists.
    Keyboard: Use Arrow Keys to navigate and Enter to launch.

Columns & Sorting

Click the headers (Name, Anno, ROM, Count) to sort the list. The "Count" column tracks how many times you have played a specific ROM.
Configuration Files

The script creates several JSON files in the root directory to store your data:

    game_list.json: The database of your ROMs (generated from MAME).
    play_counts.json: Stores the number of launches per game.
    lists.json: Stores your custom user-defined lists.
