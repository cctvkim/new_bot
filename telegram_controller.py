import logging
import threading
import time
import telebot
from telebot.apihelper import ApiTelegramException


class TelegramController:
    def __init__(self, token, channel_id, on_hold, on_start, get_status_text):
        self.bot = telebot.TeleBot(token)   # parse_mode 제거
        self.channel_id = channel_id
        self.on_hold = on_hold
        self.on_start = on_start
        self.get_status_text = get_status_text
        self.stop_flag = False
        self._configure()

    def _configure(self):
        @self.bot.message_handler(commands=['hold'])
        def handle_hold(message):
            self.on_hold()
            self.bot.reply_to(message, "자동매매 HOLD")

        @self.bot.message_handler(commands=['start'])
        def handle_start(message):
            self.on_start()
            self.bot.reply_to(message, "자동매매 START")

        @self.bot.message_handler(commands=['status'])
        def handle_status(message):
            self.bot.reply_to(message, self.get_status_text())

        @self.bot.message_handler(commands=['help'])
        def handle_help(message):
            self.bot.reply_to(message, "/hold\n/start\n/status")

    def start_background(self):
        t = threading.Thread(target=self._polling_loop, daemon=True)
        t.start()
        return t

    def _polling_loop(self):
        while not self.stop_flag:
            try:
                self.bot.delete_webhook(drop_pending_updates=True)
                self.bot.polling(
                    non_stop=True,
                    skip_pending=True,
                    timeout=20,
                    long_polling_timeout=30,
                )
            except ApiTelegramException as e:
                logging.error(f"Telegram API error: {e}")
                time.sleep(10)
            except Exception as e:
                logging.error(f"Telegram polling error: {e}")
                time.sleep(10)

    def stop(self):
        self.stop_flag = True