"""Account continuity: logging out must never discard room ownership."""
import json
import secrets
import subprocess
import sys
import unittest

from test_api_workflows import LocalServer, ROOT


class AccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LocalServer()
        cls.addClassCleanup(cls.server.close)
        cls.server.start()

    def client(self):
        client = self.server.client()
        self.addCleanup(client.close)
        response = client.get('/api/bootstrap')
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def register(self, client):
        credentials = {'username': '账号' + secrets.token_hex(4), 'password': 'regression-password'}
        response = client.post('/api/auth/register', json=credentials)
        self.assertEqual(response.status_code, 200, response.text)
        return credentials

    def create(self, client):
        response = client.post('/api/rooms', json={'username': '账号房主', 'scenario': {'title': '登录后找回'}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_logout_and_new_device_login_restore_host(self):
        host = self.client()
        credentials = self.register(host)
        room = self.create(host)
        self.assertEqual(host.post('/api/auth/logout').status_code, 200)
        other_device = self.client()
        response = other_device.post('/api/auth/login', json=credentials)
        self.assertEqual(response.status_code, 200, response.text)
        restored = other_device.get(f"/api/rooms/{room['code']}").json()
        self.assertEqual(restored['me']['id'], room['host_id'])
        self.assertEqual(other_device.get('/api/rooms').json()[0]['id'], room['id'])
        self.assertEqual(other_device.get(f"/api/rooms/{room['id']}/provider").status_code, 200)

    def test_registration_binds_existing_browser_room(self):
        host = self.client()
        identity = host.get('/api/bootstrap').json()['user_id']
        script = """
import sys
from wedecide import store,domain
from wedecide.models import CreateRoom
room=domain.new_room(sys.argv[1],CreateRoom(username='旧房主',scenario={'title':'原有匿名房间'}),8)
room['code']='LEGACY01'
with store.connect() as db:
    db.execute('INSERT INTO rooms VALUES(?,?,?,?,?,?)',(room['id'],room['code'],room['state'],room['revision'],room['updated'],store.dumps(room)))
print(room['id'])
"""
        result = subprocess.run([sys.executable, '-c', script, identity], cwd=ROOT, env=self.server.env, check=True, capture_output=True, text=True)
        room_id = result.stdout.strip()
        credentials = self.register(host)
        self.assertEqual(host.get('/api/bootstrap').json()['user_id'], identity)
        device = self.client()
        self.assertEqual(device.post('/api/auth/login', json=credentials).status_code, 200)
        restored = device.get(f'/api/rooms/{room_id}').json()
        self.assertEqual(restored['host_id'], restored['me']['id'])
        self.assertEqual(restored['scenario']['title'], '原有匿名房间')

    def test_member_login_restores_approval_without_duplicate_join(self):
        host = self.client()
        self.register(host)
        room = self.create(host)
        guest = self.client()
        credentials = self.register(guest)
        joined = guest.post(f"/api/join/{room['code']}", json={'username': '账号成员'}).json()
        room = host.get(f"/api/rooms/{room['id']}").json()
        response = host.post(f"/api/rooms/{room['id']}/actions", json={'revision': room['revision'], 'action': 'approve', 'payload': {'member_id': joined['me']['id']}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(guest.post('/api/auth/logout').status_code, 200)
        device = self.client()
        self.assertEqual(device.post('/api/auth/login', json=credentials).status_code, 200)
        restored = device.get(f"/api/rooms/{room['id']}").json()
        self.assertEqual(restored['me']['status'], 'approved')
        self.assertEqual(len(restored['members']), 2)

    def test_new_room_requires_recoverable_account(self):
        guest = self.client()
        response = guest.post('/api/rooms', json={'username': '未绑定', 'scenario': {'title': '需要账号'}})
        self.assertEqual(response.status_code, 401)

    def test_current_account_and_duplicate_name_are_explicit(self):
        owner = self.client()
        credentials = self.register(owner)
        self.assertEqual(owner.get('/api/bootstrap').json()['account']['username'], credentials['username'])
        response = self.client().post('/api/auth/register', json=credentials)
        self.assertEqual(response.status_code, 409)

    def test_logout_one_device_keeps_other_device_signed_in(self):
        host = self.client()
        credentials = self.register(host)
        room = self.create(host)
        device = self.client()
        self.assertEqual(device.post('/api/auth/login', json=credentials).status_code, 200)
        self.assertEqual(host.post('/api/auth/logout').status_code, 200)
        self.assertEqual(device.get(f"/api/rooms/{room['id']}").status_code, 200)


if __name__ == '__main__':
    unittest.main()
