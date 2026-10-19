"""Small username/password accounts sharing the existing member identity."""
import asyncio
import hashlib
import secrets
import sqlite3
import time
import unicodedata

from fastapi import APIRouter, HTTPException, Request, Response

from . import domain, store
from .cli import verify_password
from .config import SECURE_COOKIE
from .models import AccountCredentials

router = APIRouter(prefix='/api/auth')
password_slots = asyncio.Semaphore(2)


def username_key(value):
    return unicodedata.normalize('NFKC', value.strip()).casefold()


def current(request):
    session = store.session(request.cookies.get('wd_session'))
    if not session or session['admin']:
        return None
    return store.account(session['user_id'])


def required(request):
    account = current(request)
    domain.require(account is not None, '请先登录或注册账号，方便以后找回自己的房间', 401)
    return account['user_id']


def hash_password(password):
    salt = secrets.token_bytes(16)
    result = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ':' + result.hex()


def signed_in(request, response, user_id):
    token = store.make_session(user_id=user_id)
    with store.connect() as db:
        db.execute('DELETE FROM sessions WHERE token=? AND admin=0', (store.digest(request.cookies.get('wd_session', '')),))
    response.set_cookie('wd_session', token, max_age=2592000, httponly=True, secure=SECURE_COOKIE, samesite='lax', path='/')
    return {'account': store.account(user_id)}


@router.post('/register')
async def register(data: AccountCredentials, request: Request, response: Response):
    session = store.session(request.cookies.get('wd_session'))
    user_id = session['user_id'] if session and not session['admin'] else store.new_id()
    domain.require(store.account(user_id) is None, '当前已经登录，请先退出后再注册其他账号', 409)
    async with password_slots:
        encoded = await asyncio.to_thread(hash_password, data.password)
    try:
        with store.transaction() as db:
            db.execute('INSERT INTO accounts(user_id,username,username_key,password,created) VALUES(?,?,?,?,?)',
                       (user_id, data.username, username_key(data.username), encoded, time.time()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, '这个用户名已被使用，请换一个用户名或直接登录') from None
    return signed_in(request, response, user_id)


@router.post('/login')
async def login(data: AccountCredentials, request: Request, response: Response):
    with store.connect() as db:
        row = db.execute('SELECT user_id,password FROM accounts WHERE username_key=?', (username_key(data.username),)).fetchone()
    async with password_slots:
        valid = row is not None and await asyncio.to_thread(verify_password, data.password, row['password'])
    domain.require(valid, '用户名或密码不正确', 401)
    previous = store.session(request.cookies.get('wd_session'))
    if previous and not previous['admin'] and previous['user_id'] != row['user_id'] and store.account(previous['user_id']) is None:
        domain.require(not store.has_rooms(previous['user_id']), '当前浏览器还有未绑定的房间，请先注册绑定此身份；已有账号可在其他浏览器登录', 409)
    return signed_in(request, response, row['user_id'])


@router.post('/logout')
async def logout(request: Request, response: Response):
    required(request)
    with store.connect() as db:
        db.execute('DELETE FROM sessions WHERE token=? AND admin=0', (store.digest(request.cookies.get('wd_session', '')),))
    response.delete_cookie('wd_session', path='/')
    return {'ok': True}
