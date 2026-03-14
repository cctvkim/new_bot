import logging


class Notifier:
    def __init__(self, telegram_bot=None, channel_id=None):
        self.telegram_bot = telegram_bot
        self.channel_id = channel_id

    def send(self, message: str):
        logging.info(message)
        if not self.telegram_bot or not self.channel_id:
            return
        try:
            self.telegram_bot.send_message(self.channel_id, message)
        except Exception as e:
            logging.error(f"Telegram send failed: {e}")