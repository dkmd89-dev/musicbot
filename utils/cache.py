from functools import lru_cache
from cachetools import LFUCache
import threading


# Threadsafe Cache für Strings
class StringCache:
    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()

    def decorator(self, func):
        def wrapper(arg):
            key = str(arg)
            with self.lock:
                if key in self.cache:
                    return self.cache[key]
                result = func(arg)
                self.cache[key] = result
                return result

        return wrapper


string_cache = StringCache()


# LFU Cache für komplexe Objekte
class LFUDecorator:
    def __init__(self, maxsize=128):
        self.cache = LFUCache(maxsize)
        self.lock = threading.Lock()

    def decorator(self, func):
        def wrapper(arg):
            key = str(arg)
            with self.lock:
                if key in self.cache:
                    return self.cache[key]
                result = func(arg)
                self.cache[key] = result
                return result

        return wrapper


lfu_cache = LFUDecorator()
