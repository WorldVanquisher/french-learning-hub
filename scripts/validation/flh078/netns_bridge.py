#!/usr/bin/env python3
"""FLH-078 byte bridge between a loopback TCP port and a Unix socket.

  netns_bridge.py inner SOCK PORT   listen on SOCK, forward to 127.0.0.1:PORT
  netns_bridge.py outer PORT SOCK   listen on 127.0.0.1:PORT, forward to SOCK

Used to reach a demo server that runs in a network namespace with only
loopback (so it cannot reach any encoder or other host): the inner side runs
inside the namespace, the outer side outside it, and the socket file is shared
through the filesystem. Stdlib only; runs until killed; logs nothing.
"""
import os
import socket
import sys
import threading


def pump(src, dst):
    try:
        while True:
            b = src.recv(65536)
            if not b:
                break
            dst.sendall(b)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def serve(listener, connect):
    while True:
        c, _ = listener.accept()
        try:
            u = connect()
        except OSError:
            c.close()
            continue
        threading.Thread(target=pump, args=(c, u), daemon=True).start()
        threading.Thread(target=pump, args=(u, c), daemon=True).start()


def main():
    mode = sys.argv[1]
    if mode == "inner":
        sock, port = sys.argv[2], int(sys.argv[3])
        if os.path.exists(sock):
            sys.exit("refused: %s exists" % sock)
        lst = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        lst.bind(sock)
        os.chmod(sock, 0o600)
        lst.listen(64)
        serve(lst, lambda: socket.create_connection(("127.0.0.1", port)))
    elif mode == "outer":
        port, sock = int(sys.argv[2]), sys.argv[3]
        lst = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lst.bind(("127.0.0.1", port))
        lst.listen(64)

        def connect():
            u = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            u.connect(sock)
            return u

        serve(lst, connect)
    else:
        sys.exit("usage: netns_bridge.py inner SOCK PORT | outer PORT SOCK")


if __name__ == "__main__":
    main()
