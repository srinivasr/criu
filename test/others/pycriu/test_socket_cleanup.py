#!/usr/bin/env python3
import os
import signal
import socket
import sys
import time

# Add ../../../lib so we can import pycriu
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "../../../lib"))
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

import pycriu  # noqa: E402
from pycriu.criu import CRIUExceptionInternal  # noqa: E402
from pycriu.criu import criu as criu_class  # noqa: E402


def make_req(criu, keep_open):
    req = pycriu.rpc.criu_req(type=pycriu.rpc.CHECK, keep_open=keep_open)
    req.opts.MergeFrom(criu.opts)
    return req


def fail(msg):
    print("FAIL: %s" % msg)
    return 1


def main():
    # A failed keep_open request closes the connection, so the next
    # request reconnects instead of reusing it.
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    criu = criu_class()
    criu.use_fd(client.fileno())
    req = make_req(criu, True)
    server.send(pycriu.rpc.criu_resp(type=pycriu.rpc.CHECK,
                                     success=False).SerializeToString())
    resp = criu._send_req_and_recv_resp(req)
    if resp.success:
        return fail("failed keep_open request returned success")
    if criu.sk is not None:
        return fail("failed keep_open request kept the socket cached")
    if server.recv(4096) != req.SerializeToString():
        return fail("server got a different request")
    req = make_req(criu, False)
    server.send(pycriu.rpc.criu_resp(type=pycriu.rpc.CHECK,
                                     success=True).SerializeToString())
    resp = criu._send_req_and_recv_resp(req)
    if not resp.success:
        return fail("request after failed keep_open did not reconnect")
    server.close()
    client.close()

    # A normal request closes a socket kept by a keep_open request.
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    criu = criu_class()
    criu.use_fd(client.fileno())
    req = make_req(criu, True)
    server.send(pycriu.rpc.criu_resp(type=pycriu.rpc.CHECK,
                                     success=True).SerializeToString())
    criu._send_req_and_recv_resp(req)
    if criu.sk is None:
        return fail("successful keep_open request did not keep the socket")
    req = make_req(criu, False)
    server.send(pycriu.rpc.criu_resp(type=pycriu.rpc.CHECK,
                                     success=True).SerializeToString())
    criu._send_req_and_recv_resp(req)
    if criu.sk is not None:
        return fail("normal request left the closed socket cached")

    # A broken cached socket is dropped after an internal error.
    req = make_req(criu, True)
    server.send(pycriu.rpc.criu_resp(type=pycriu.rpc.CHECK,
                                     success=True).SerializeToString())
    criu._send_req_and_recv_resp(req)
    if criu.sk is None:
        return fail("successful keep_open request did not keep the socket")
    criu.sk.close()
    try:
        criu._send_req_and_recv_resp(make_req(criu, False))
        return fail("request on a broken socket did not raise")
    except CRIUExceptionInternal:
        # Expected: the broken socket raises an internal error.
        pass
    if criu.sk is not None:
        return fail("broken socket stayed cached after the error")
    server.close()
    client.close()

    # A failed service connection cleans up its socket.
    criu = criu_class()
    criu.use_sk(os.path.join(SCRIPT_DIR, "no-such-dir", "service.socket"))
    try:
        criu._comm.connect(False)
        return fail("connect to a missing socket did not raise")
    except FileNotFoundError:
        # Expected: there is no socket to connect to.
        pass
    if criu._comm.sk is not None:
        return fail("failed connect kept the socket")

    # A request to a binary that exits without serving reaps the child.
    criu = criu_class()
    criu.use_binary("/bin/true")
    try:
        criu._send_req_and_recv_resp(make_req(criu, False))
    except CRIUExceptionInternal:
        # Expected: the binary exits before it can serve.
        pass
    try:
        os.waitpid(-1, os.WNOHANG)
        return fail("request to a dead binary left an unreaped child")
    except ChildProcessError:
        # No unreaped child left: the request already reaped it.
        pass

    # disconnect() accepts a child the caller reaped itself.
    comm = criu_class()._comm
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
    comm.daemon = False
    comm.swrk = pid
    try:
        comm.disconnect()
        comm.disconnect()
    except ChildProcessError:
        return fail("disconnect raised for an already reaped child")
    if comm.swrk is not None:
        return fail("disconnect kept the reaped child pid")

    # disconnect() accepts a child the kernel reaped because the caller
    # ignores SIGCHLD.
    old_handler = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    try:
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        for _ in range(100):
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                break
            time.sleep(0.05)
        else:
            return fail("kernel did not reap the child with SIGCHLD ignored")
        comm = criu_class()._comm
        comm.daemon = False
        comm.swrk = pid
        try:
            comm.disconnect()
        except ChildProcessError:
            return fail("disconnect raised with SIGCHLD ignored")
        if comm.swrk is not None:
            return fail("disconnect kept the child pid with SIGCHLD ignored")
    finally:
        signal.signal(signal.SIGCHLD, old_handler)

    print("PASS")
    return 0

if __name__ == "__main__":
    sys.exit(main())
