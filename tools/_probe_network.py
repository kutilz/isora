"""Root-cause probe #2: break down where time actually goes on the path to
Gemini's API from the DEVICE itself: DNS resolve, TCP connect, TLS handshake,
request send, time-to-first-byte. This separates "our link is slow" from
"Google's server/thinking is slow". Also does a raw throughput check (download
a few hundred KB) to sanity-check the user's claimed 2MB/s. Scratch, delete.
"""
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=60):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


dev = r'''
import socket, ssl, time

HOST = "generativelanguage.googleapis.com"

def probe(n):
    t0 = time.monotonic()
    addrs = socket.getaddrinfo(HOST, 443, socket.AF_INET, socket.SOCK_STREAM)
    t_dns = time.monotonic()
    ip = addrs[0][4][0]

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(20)
    sock.connect((ip, 443))
    t_tcp = time.monotonic()

    ctx = ssl.create_default_context()
    ssock = ctx.wrap_socket(sock, server_hostname=HOST)
    t_tls = time.monotonic()

    req = (
        "GET /$discovery/rest?version=v1beta HTTP/1.1\r\n"
        f"Host: {HOST}\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    ssock.sendall(req)
    t_sent = time.monotonic()

    first = ssock.recv(1)
    t_first_byte = time.monotonic()

    total = 0
    while True:
        chunk = ssock.recv(65536)
        if not chunk:
            break
        total += len(chunk)
    t_done = time.monotonic()
    ssock.close()

    print(f"run {n}: ip={ip}")
    print(f"  dns          = {(t_dns - t0)*1000:.0f}ms")
    print(f"  tcp connect  = {(t_tcp - t_dns)*1000:.0f}ms")
    print(f"  tls handshake= {(t_tls - t_tcp)*1000:.0f}ms")
    print(f"  send req     = {(t_sent - t_tls)*1000:.0f}ms")
    print(f"  time-to-1st-byte(after send) = {(t_first_byte - t_sent)*1000:.0f}ms")
    print(f"  rest of body = {(t_done - t_first_byte)*1000:.0f}ms  ({total+1} bytes)")
    print(f"  TOTAL        = {(t_done - t0)*1000:.0f}ms")

for i in range(3):
    try:
        probe(i)
    except Exception as e:
        print("run", i, "FAILED:", e)
'''

sftp = c.open_sftp()
with sftp.open("/tmp/_probe_net_remote.py", "w") as f:
    f.write(dev)
sftp.close()

p(sh("python3 /tmp/_probe_net_remote.py", t=90))
p(sh("rm -f /tmp/_probe_net_remote.py; echo done"))

c.close()
