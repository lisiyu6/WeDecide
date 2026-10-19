import asyncio
import time
from collections import defaultdict


class Hub:
    """One-slot queues coalesce bursts; clients always fetch authoritative state."""
    def __init__(self):
        self.listeners = defaultdict(dict)
        self.closing = False

    def online(self, room_id):
        return {identity for identity, _ in self.listeners.get(room_id, {}).values()}

    def subscribe(self, room_id, user_id):
        if self.closing:
            return None
        listeners = self.listeners[room_id]
        if len(listeners) >= 256 or sum(x[0] == user_id for x in listeners.values()) >= 3:
            return None
        key, queue = object(), asyncio.Queue(maxsize=1)
        listeners[key] = (user_id, queue)
        self.publish(room_id)
        return key, queue

    def remove(self, room_id, key):
        listeners = self.listeners.get(room_id)
        if listeners:
            listeners.pop(key, None)
            if not listeners:
                self.listeners.pop(room_id, None)
        self.publish(room_id)

    def publish(self, room_id):
        for _, queue in self.listeners.get(room_id, {}).values():
            if not queue.full():
                queue.put_nowait(time.time())

    def close(self):
        """Wake every stream, including readers blocked on a quiet room queue."""
        self.closing = True
        for listeners in self.listeners.values():
            for _, queue in listeners.values():
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(None)
