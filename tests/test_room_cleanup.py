"""Room deletion releases only its own AI work and live subscriptions."""
import asyncio
import unittest
from unittest.mock import patch

from wedecide.ai import Coordinator


class RoomCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_deleting_room_cancels_its_ai_without_interrupting_other_room(self):
        coordinator = Coordinator()
        self.addAsyncCleanup(coordinator.close)
        release = asyncio.Event()
        started = {room: asyncio.Event() for room in ('deleted', 'retained')}
        replies = []

        async def operation(room):
            started[room].set()
            await release.wait()
            return room

        async def completed(result, error):
            replies.append((result, error))

        with patch('wedecide.ai.store.settings', return_value={'ai_concurrency': 2, 'ai_queue_limit': 8}):
            for room in started:
                coordinator.submit((room, 'member'), lambda room=room: operation(room), completed)
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), timeout=2)
            await coordinator.cancel_room('deleted')
            self.assertNotIn(('deleted', 'member'), coordinator.pending)
            self.assertIn(('retained', 'member'), coordinator.pending)
            self.assertEqual(coordinator.running, 1)
            release.set()
            await asyncio.wait_for(asyncio.gather(*coordinator.pending.values()), timeout=2)
        self.assertEqual(replies, [('retained', None)])
        self.assertFalse(coordinator.pending)
        self.assertEqual(coordinator.running, 0)

    async def test_deleting_room_also_releases_ai_cancelled_before_start(self):
        coordinator = Coordinator()
        self.addAsyncCleanup(coordinator.close)
        invoked = []

        async def operation():
            invoked.append('started')

        async def completed(result, error):
            invoked.append('completed')

        with patch('wedecide.ai.store.settings', return_value={'ai_concurrency': 1, 'ai_queue_limit': 8}):
            coordinator.submit(('deleted', 'member'), operation, completed)
            await coordinator.cancel_room('deleted')
        self.assertFalse(coordinator.pending)
        self.assertFalse(invoked)
        self.assertEqual(coordinator.running, 0)
