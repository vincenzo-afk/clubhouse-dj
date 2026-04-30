import logging

logger = logging.getLogger(__name__)

class ClubhouseClient:
    def __init__(self, credentials):
        self.credentials = credentials
        self.room_id = None
        logger.info("ClubhouseClient initialized.")

    def join_room(self, room_id):
        self.room_id = room_id
        logger.info(f"Joining room: {room_id}")
        # API call implementation goes here
        return True

    def leave_room(self):
        if self.room_id:
            logger.info(f"Leaving room: {self.room_id}")
            self.room_id = None
        return True
