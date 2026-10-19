import argparse
import getpass
import hashlib
import hmac
import secrets
from . import store
from .config import HOST, PORT


def verify_password(password, encoded):
    try:
        salt, expected = encoded.split(":", 1)
        result = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(result, expected)
    except (ValueError, TypeError):
        return False


def main():
    parser = argparse.ArgumentParser(prog="wedecide")
    subs = parser.add_subparsers(dest="command", required=True)
    serve = subs.add_parser("serve", help="启动单进程 HTTP 服务")
    serve.add_argument("--host", default=HOST)
    serve.add_argument("--port", type=int, default=PORT)
    subs.add_parser("admin-password", help="交互设置管理员密码并注销已有管理员会话")
    args = parser.parse_args()
    store.init()
    if args.command == "admin-password":
        password = getpass.getpass("新管理员密码（至少 10 位）：")
        if len(password) < 10 or len(password) > 256:
            parser.error("密码须为 10–256 位")
        if password != getpass.getpass("再次输入："):
            parser.error("两次输入不同")
        salt = secrets.token_bytes(16)
        value = salt.hex() + ":" + hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
        with store.transaction() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('admin_password',?)", (value,))
            db.execute("DELETE FROM sessions WHERE admin=1")
        print("管理员密码已更新。通过 /admin 访问管理页。")
    else:
        from .server import run
        run(args.host, args.port)

if __name__ == "__main__":
    main()
