# ClubDJ Bot

An automated DJ bot for Clubhouse rooms.

## Project Structure

- `main.py`: Entry point for the bot.
- `config.json`: Configuration settings and credentials.
- `bot/`: Core logic for the bot.
  - `clubhouse_client.py`: Handles interaction with the Clubhouse API.
  - `audio_player.py`: Manages audio playback using FFmpeg/PyAudio.
  - `silence_detector.py`: Detects silence to manage transitions.
  - `queue_manager.py`: Manages the song queue.
  - `command_handler.py`: Processes in-room commands.
  - `announcer.py`: Handles text-to-speech announcements.
  - `scheduler.py`: Manages scheduled tasks (e.g., auto-start).
- `playlist/`: Storage for song lists and default tracks.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Configure `config.json` with your credentials.
3. Run the bot:
   ```bash
   python main.py
   ```
