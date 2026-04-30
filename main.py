import json
import logging
from bot.clubhouse_client import ClubhouseClient
from bot.audio_player import AudioPlayer
from bot.queue_manager import QueueManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

def main():
    config = load_config()
    logger.info("Starting ClubDJ Bot...")
    
    # Initialize components
    queue = QueueManager()
    player = AudioPlayer(config['settings']['volume'])
    client = ClubhouseClient(config['clubhouse'])
    
    # Main loop logic would go here
    logger.info("Bot components initialized. Ready to connect.")

if __name__ == "__main__":
    main()
