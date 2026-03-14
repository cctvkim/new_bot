import time


class TTLCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        item = self.store.get(key)
        if not item:
            return None

        value, expires_at = item
        if time.time() > expires_at:
            self.store.pop(key, None)
            return None

        return value

    def set(self, key, value, ttl: float):
        self.store[key] = (value, time.time() + ttl)

    def clear(self, key=None):
        if key is None:
            self.store.clear()
        else:
            self.store.pop(key, None)