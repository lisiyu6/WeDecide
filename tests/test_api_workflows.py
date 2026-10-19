"""Black-box regressions against an isolated real server and a local AI fixture."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import httpx

ROOT = Path(__file__).resolve().parents[1]


class LocalServer:
    def __init__(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wedecide-regression-')
        self.log = tempfile.TemporaryFile(mode='w+')
        self.env = {**os.environ, 'WEDECIDE_DATA_DIR': self.directory.name,
                    'WEDECIDE_PUBLIC_URL': '', 'WEDECIDE_ALLOWED_ORIGINS': '',
                    'WEDECIDE_SECURE_COOKIE': 'false', 'PYTHONDONTWRITEBYTECODE': '1'}
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.url = f'http://127.0.0.1:{self.port}'
        self.process = None

    def start(self):
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'wedecide.cli', 'serve', '--host', '127.0.0.1', '--port', str(self.port)],
            cwd=ROOT, env=self.env, stdout=self.log, stderr=self.log,
        )
        deadline = time.monotonic() + 8
        with self.client() as client:
            while time.monotonic() < deadline:
                try:
                    if client.get('/').status_code == 200:
                        return self
                except httpx.TransportError:
                    pass
                if self.process.poll() is not None:
                    break
                time.sleep(.05)
        raise RuntimeError('Isolated server did not start: ' + self.logs())

    def client(self):
        return httpx.Client(base_url=self.url, trust_env=False, timeout=8)

    def logs(self):
        self.log.flush()
        self.log.seek(0)
        return self.log.read()

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)

    def close(self):
        self.stop()
        self.log.close()
        self.directory.cleanup()


class ProviderFixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, value):
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        return self.headers.get('Authorization') == 'Bearer regression-only-key'

    def do_GET(self):
        if not self.authorized():
            return self.respond(401, {'error': 'fixture auth mismatch'})
        if self.path in {'/v1/models', '/models'}:
            return self.respond(200, {'data': [{'id': 'regression-chat'}, {'id': 'regression-small'}]})
        self.respond(404, {'error': 'unknown fixture route'})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
        if not self.authorized():
            return self.respond(401, {'error': 'fixture auth mismatch'})
        if self.path not in {'/v1/chat/completions', '/chat/completions'}:
            return self.respond(404, {'error': 'unknown fixture route'})
        if body.get('model') != 'regression-chat' or not body.get('messages'):
            return self.respond(400, {'error': 'missing model or messages'})
        time.sleep(.15)
        content = '本地接口回归回复'
        if 'Preference JSON Schema' in body['messages'][0]['content']:
            content = json.dumps({'budget_max': 200, 'notes': ['候选餐厅待补充']}, ensure_ascii=False)
        self.respond(200, {'choices': [{'message': {'role': 'assistant', 'content': content}}]})


class ApiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LocalServer()
        cls.addClassCleanup(cls.server.close)
        cls.password = secrets.token_urlsafe(18)
        password = subprocess.run(
            [sys.executable, '-m', 'wedecide.cli', 'admin-password'], cwd=ROOT,
            env=cls.server.env, input=cls.password + '\n' + cls.password + '\n',
            text=True, capture_output=True,
        )
        if password.returncode:
            raise RuntimeError('Test administrator initialization failed')
        cls.server.start()
        cls.upstream = ThreadingHTTPServer(('127.0.0.1', 0), ProviderFixture)
        cls.thread = threading.Thread(target=cls.upstream.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.upstream.server_close)
        cls.addClassCleanup(cls.upstream.shutdown)
        cls.upstream_url = f'http://127.0.0.1:{cls.upstream.server_port}'
        cls.admin = cls.server.client()
        cls.addClassCleanup(cls.admin.close)
        response = cls.admin.post('/api/admin/login', json={'password': cls.password})
        if response.status_code != 200:
            raise RuntimeError('Test administrator login failed')
        config = cls.admin.get('/api/admin/settings').json()
        response = cls.admin.put('/api/admin/settings', json={'revision': config['revision'], 'max_rooms': 64})
        if response.status_code != 200:
            raise RuntimeError('Test room capacity setup failed')

    def client(self):
        client = self.server.client()
        self.addCleanup(client.close)
        response = client.get('/api/bootstrap')
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def room(self, client=None, **changes):
        client = client or self.client()
        body = {'username': '回归房主', 'scenario': {'title': self._testMethodName, 'city': '杭州', 'date': '2026-10-24'}, 'demo': True}
        body.update(changes)
        response = client.post('/api/rooms', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return client, response.json()

    def action(self, client, room, action, **payload):
        response = client.post(f"/api/rooms/{room['id']}/actions", json={'revision': room['revision'], 'action': action, 'payload': payload})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def pair(self):
        host, room = self.room()
        guest = self.client()
        response = guest.post(f"/api/join/{room['code']}", json={'username': '回归成员'})
        self.assertEqual(response.status_code, 200, response.text)
        pending = response.json()
        room = host.get(f"/api/rooms/{room['id']}").json()
        room = self.action(host, room, 'approve', member_id=pending['me']['id'])
        return host, guest, room

    def provider(self, endpoint='/v1/chat/completions'):
        return {'id': 'regression', 'name': '本地回归接口', 'protocol': 'openai',
                'endpoint': self.upstream_url + endpoint, 'model': 'regression-chat',
                'api_key': 'regression-only-key'}

    def configure(self, host, room, endpoint='/v1/chat/completions'):
        response = host.put(f"/api/rooms/{room['id']}/provider", json={
            'revision': room['revision'], 'provider': self.provider(endpoint)})
        self.assertEqual(response.status_code, 200, response.text)
        return host.get(f"/api/rooms/{room['id']}").json()

    def replies(self, client, room):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            messages = client.get(f"/api/rooms/{room['id']}/messages").json()
            answers = [m for m in messages if m['role'] == 'assistant']
            if answers:
                return answers
            time.sleep(.03)
        self.fail('AI reply was not persisted before timeout')

    def test_create_reload_and_room_assets(self):
        host, room = self.room()
        self.assertEqual(host.get(f"/api/rooms/{room['code']}").json()['id'], room['id'])
        self.assertEqual(host.get('/api/rooms').json()[0]['code'], room['code'])
        for path in ('/new', f"/r/{room['code']}", '/static/app.js', '/static/preferences.js'):
            with self.subTest(path=path):
                self.assertEqual(host.get(path).status_code, 200)

    def test_join_waits_for_host_approval(self):
        host, room = self.room()
        guest = self.client()
        response = guest.post(f"/api/join/{room['code']}", json={'username': '申请者'})
        self.assertEqual(response.status_code, 200, response.text)
        pending = response.json()
        self.assertEqual(pending['me']['status'], 'pending')
        self.assertNotIn('resources', pending)
        room = host.get(f"/api/rooms/{room['id']}").json()
        self.action(host, room, 'approve', member_id=pending['me']['id'])
        self.assertEqual(guest.get(f"/api/rooms/{room['id']}").json()['me']['status'], 'approved')

    def test_members_confirm_independently_with_same_room_revision(self):
        host, guest, room = self.pair()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.action, c, room, 'preference', preference_version=0, preference={'budget_max': value}) for c, value in ((host, 300), (guest, 100))]
            results = [f.result() for f in futures]
        self.assertEqual([r['me']['preference']['budget_max'] for r in results], [300, 100])
        self.assertTrue(all(r['me']['confirmed'] for r in results))

    def test_notes_do_not_block_confirming_exact_times(self):
        host, room = self.room()
        room = self.action(host, room, 'preference', preference_version=0, preference={
            'budget_max': 500, 'available_start': 615, 'available_end': 1125, 'notes': ['候选餐厅待补充']})
        self.assertTrue(room['me']['confirmed'])
        self.assertEqual(room['me']['preference']['available_end'], 1125)
        self.assertEqual(room['me']['preference']['notes'], ['候选餐厅待补充'])

    def test_unresolved_question_does_not_silently_confirm(self):
        host, room = self.room()
        response = host.post(f"/api/rooms/{room['id']}/actions", json={'revision': room['revision'], 'action': 'preference', 'payload': {'preference_version': 0, 'preference': {'unresolved': ['必须结束的时间待确认']}}})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(host.get(f"/api/rooms/{room['id']}").json()['me']['confirmed'])

    def test_local_extraction_draft_can_be_confirmed(self):
        host, room = self.room()
        response = host.post(f"/api/rooms/{room['id']}/ai", json={'kind': 'preferences', 'text': '预算不超过 200 元，10:00 到 18:30'})
        self.assertEqual(response.status_code, 202, response.text)
        answer = self.replies(host, room)[0]
        self.assertEqual(answer['metadata']['mode'], 'local')
        draft = answer['metadata']['draft']
        self.assertEqual((draft['budget_max'], draft['available_end']), (200, 1110))
        self.assertEqual(draft['unresolved'], [])
        self.action(host, room, 'preference', preference_version=0, preference=draft)

    def test_room_models_from_unsaved_configuration(self):
        host, room = self.room()
        response = host.post(f"/api/rooms/{room['id']}/provider/models", json={'provider': self.provider()})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['models'], ['regression-chat', 'regression-small'])
        self.assertIsNone(host.get(f"/api/rooms/{room['id']}/provider").json()['provider'])

    def test_admin_models_before_saving_supplier(self):
        response = self.admin.post('/api/admin/providers/models', json={'provider': self.provider()})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('regression-chat', response.json()['models'])

    def test_saved_room_key_is_reused_when_edit_leaves_it_blank(self):
        host, room = self.room()
        room = self.configure(host, room)
        provider = host.get(f"/api/rooms/{room['id']}/provider").json()['provider']
        self.assertTrue(provider['has_key'])
        self.assertNotIn('regression-only-key', json.dumps(provider))
        provider = self.provider()
        provider['api_key'] = ''
        response = host.post(f"/api/rooms/{room['id']}/provider/models", json={'provider': provider})
        self.assertEqual(response.status_code, 200, response.text)

    def test_openai_base_url_supports_discovery_and_chat(self):
        host, room = self.room()
        room = self.configure(host, room, '/v1')
        response = host.post(f"/api/rooms/{room['id']}/provider/models", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(host.post(f"/api/rooms/{room['id']}/ai", json={'text': '基址调用回归'}).status_code, 202)
        answer = self.replies(host, room)[0]
        self.assertFalse(answer['metadata'].get('error'), answer['content'])
        self.assertEqual(answer['content'], '本地接口回归回复')

    def test_two_members_send_ai_without_waiting_for_each_other(self):
        host, guest, room = self.pair()
        room = self.configure(host, room)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(client.post, f"/api/rooms/{room['id']}/ai", json={'text': text}) for client, text in ((host, '房主自己的问题'), (guest, '成员自己的问题'))]
            responses = [f.result() for f in futures]
        self.assertEqual([r.status_code for r in responses], [202, 202])
        self.assertEqual(self.replies(host, room)[0]['content'], '本地接口回归回复')
        self.assertEqual(self.replies(guest, room)[0]['content'], '本地接口回归回复')
        self.assertNotIn('成员自己的问题', json.dumps(host.get(f"/api/rooms/{room['id']}/messages").json(), ensure_ascii=False))
        self.assertNotIn('房主自己的问题', json.dumps(guest.get(f"/api/rooms/{room['id']}/messages").json(), ensure_ascii=False))

    def test_analyze_vote_and_report_complete(self):
        host, guest, room = self.pair()
        self.action(host, room, 'preference', preference_version=0, preference={'budget_max': 500, 'budget_target': 150})
        room = self.action(guest, room, 'preference', preference_version=0, preference={'budget_max': 500})
        room = self.action(host, room, 'analyze')
        proposal = next(p for p in room['proposals'] if p['evaluation']['status'] == 'FEASIBLE')
        room = self.action(host, room, 'select', proposal_id=proposal['id'])
        room = self.action(host, room, 'start_vote')
        vote_id = room['vote']['id']
        self.action(host, room, 'vote', session_id=vote_id, choice='accept')
        room = self.action(guest, room, 'vote', session_id=vote_id, choice='accept')
        self.assertEqual(room['state'], 'APPROVED')
        report = host.get(f"/api/rooms/{room['id']}/report")
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(report.json()['result']['outcome'], 'APPROVED')

    def test_incomplete_scenario_cannot_be_marked_feasible(self):
        host, room = self.room(scenario={'title': '资料未齐'})
        room = self.action(host, room, 'preference', preference_version=0, preference={})
        room = self.action(host, room, 'analyze')
        self.assertTrue(room['proposals'])
        self.assertTrue(all(p['evaluation']['status'] == 'UNKNOWN' for p in room['proposals']))


class ShutdownTests(unittest.TestCase):
    def test_sigint_closes_open_sse_and_room_survives_restart(self):
        server = LocalServer()
        self.addCleanup(server.close)
        server.start()
        with server.client() as client:
            client.get('/api/bootstrap')
            response = client.post('/api/rooms', json={'username': '退出回归', 'scenario': {'title': '退出后保留'}})
            self.assertEqual(response.status_code, 200, response.text)
            room = response.json()
            with client.stream('GET', f"/api/rooms/{room['id']}/events") as stream:
                self.assertEqual(next(stream.iter_lines()), 'event: change')
                started = time.monotonic()
                server.process.send_signal(signal.SIGINT)
                server.process.wait(timeout=7)
                elapsed = time.monotonic() - started
            self.assertLess(elapsed, 6)
            self.assertEqual(server.process.returncode, 0, server.logs())
            self.assertNotIn('timeout graceful shutdown exceeded', server.logs())
            server.start()
            self.assertEqual(client.get(f"/api/rooms/{room['id']}").json()['scenario']['title'], '退出后保留')


if __name__ == '__main__':
    unittest.main()
