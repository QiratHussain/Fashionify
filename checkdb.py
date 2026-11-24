import os
import ssl
from urllib.parse import urlsplit, unquote

from dotenv import load_dotenv, dotenv_values
import socket
import pg8000.native

# Force IPv4 only (IPv6 to Neon hangs on this network)
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _ipv4_only

system_value = os.environ.get("DATABASE_URL")  # set in Windows BEFORE .env is read
load_dotenv()
url = os.environ.get("DATABASE_URL", "")
file_value = dotenv_values().get("DATABASE_URL")

print("System env var DATABASE_URL set?:", system_value is not None)
if system_value is not None and file_value is not None and system_value != file_value:
    print("!! System env var DIFFERS from .env -> the OLD system value is being used.")
    print("   Fix: in PowerShell run  Remove-Item Env:DATABASE_URL  then rerun.")

p = urlsplit(url)
print("scheme  :", p.scheme)
print("user    :", unquote(p.username or ""))
print("password length:", len(unquote(p.password or "")), "(raw in URL:", len(p.password or ""), ")")
print("host    :", p.hostname)
print("database:", p.path.lstrip("/"))
print("query   :", p.query or "(none)")

try:
    con = pg8000.native.Connection(
        user=unquote(p.username or ""),
        password=unquote(p.password or ""),
        host=p.hostname,
        port=p.port or 5432,
        database=p.path.lstrip("/"),
        ssl_context=ssl.create_default_context(),
        timeout=15,
    )
    print("CONNECTED OK:", con.run("select current_user, version()")[0][0])
    con.close()
except Exception as e:
    print("FAILED:", repr(e))