#!/usr/bin/python
#
# Resource agent for a zope zeo server.
#
#  primitive zeo ocf:upfront:zeo  params \
#    zeoctl="/home/zope/bin/zeoserver" \
#    zeosock="/home/zope/var/zeo.sock" \
#    zeouser="zope" \
#    op start   timeout="3600s" on-fail="stop" \
#    op stop    timeout="60s" on-fail="block" \
#    op monitor timeout="29s" interval="30s" on-fail="restart" \

import sys
import re
import socket
import os
import pickle
import pwd
import subprocess
import shlex
import syslog
from ctypes import cdll
import logging

# Set up logging to HAlogd
class HALogStream(object):
    def __init__(self):
        try:
            self.libplumb = cdll.LoadLibrary("libplumb.so.2")
            self.libplumb.cl_log_set_uselogd(True)
        except OSError:
            self.libplumb = None

    def write(self, ob):
        if self.libplumb is not None:
            self.libplumb.cl_log(syslog.LOG_INFO, ob.encode('utf8'))

    def close(self):
        pass

    def flush(self):
        pass

class HALogHandler(logging.StreamHandler):
    def __init__(self):
        self.stream = HALogStream()
        logging.StreamHandler.__init__(self, self.stream)

    def close(self):
        self.flush()
        self.stream.close()
        logging.StreamHandler.close(self)

    def emit(self, record):
        logging.StreamHandler.emit(self, record)

logger = logging.getLogger("ha.pgsql")
logger.propagate = False
handler = HALogHandler()
handler.setLevel(logging.INFO)
logger.addHandler(handler)

# This line here for debugging only
#fh = logging.FileHandler('/tmp/halog')
#fh.setFormatter(logging.Formatter(fmt='%(asctime)s %(message)s'))
#logger.addHandler(fh)

logger.setLevel(logging.INFO)

# Decorators for dropping privileges and forking
def fork_and_exec(fn):
    def _fork_and_run(*args, **kwargs):
        readend, writeend = os.pipe()
        readend = os.fdopen(readend, "r")
        writeend = os.fdopen(writeend, "w")
        pid = os.fork()
        if pid==0:
            # =-=-=-= Child process starts =-=-=-=
            readend.close()
            result = fn(*args, **kwargs)
            pickle.dump(result, writeend)
            writeend.flush()
            os._exit(0)
            # =-=-=-= Child process ends =-=-=-=
        writeend.close()
        result = pickle.load(readend)
        pid, status = os.waitpid(pid, 0)
        return result
    return _fork_and_run

def drop_privileges(user):
    def _wrap(fn):
        def _new(*args, **kwargs):
            pw = pwd.getpwnam(user)
            os.setregid(pw[3], pw[3])
            os.setreuid(pw[2], pw[2])
            return fn(*args, **kwargs)
        return _new
    return _wrap

class CommandFailed(Exception):
    def __init__(self, code, msg):
        super(CommandFailed, self).__init__(self, code, msg)
        self.code = code
        self.msg = msg

def sh(command):
    p = subprocess.Popen(shlex.split(command),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    p.wait()
    response = p.stdout.read()
    if p.returncode != 0:
        raise CommandFailed(p.returncode, response)
    return response

def send_zeo_action(sockname, action):
    """Send an action to the zdrun server and return the response.
       Return None if the server is not up or any other error happened. """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(sockname)
        sock.send(action + "\n")
        sock.shutdown(1) # We're not writing any more
        response = ""
        while 1:
            data = sock.recv(1000)
            if not data:
                break
            response += data
        sock.close()
        return response
    except socket.error, msg:
        return None

def get_zeo_status(sockname):
    resp = send_zeo_action(sockname, "status")
    if not resp:
        return 0
    m = re.search("(?m)^application=(\d+)$", resp)
    if not m:
        return 0
    return int(m.group(1))

class ResourceAgent(object):
    def __init__(self):
        self._actions = {
            'start': self.start,
            'stop': self.stop,
            'status': self.status,
            'monitor': self.monitor,
            'meta-data': self.metadata,
            'methods': self.methods
        }
        self.resourcename = os.environ.get('OCF_RESOURCE_INSTANCE', 'zeo'),
        self.zeoctl = os.environ.get('OCF_RESKEY_zeoctl', '/home/zope/bin/zeoserver')
        self.zeosock = os.environ.get('OCF_RESKEY_zeosock', '/home/zope/var/zeo.sock')
        self.zeouser = os.environ.get('OCF_RESKEY_zeouser', 'zope')

    def _zeoctl(self, action):
        cmd = "%s %s" % (self.zeoctl, action)
        logger.info("calling %s", cmd)
        try:
            sh(cmd)
        except CommandFailed, e:
            logger.info(e)
            return 1
        return 0

    def _status(self):
        return get_zeo_status(self.zeosock) > 0

    def start(self):
        if not self._status():
            _c = drop_privileges(self.zeouser)(self._zeoctl)
            _c = fork_and_exec(_c)
            return _c('start')
        return 0

    def stop(self):
        if self._status():
            _c = drop_privileges(self.zeouser)(self._zeoctl)
            fork_and_exec(_c)('stop')
        if self._status():
            return 7
        return 0

    def monitor(self):
        if self._status():
            return 0
        return 7

    def metadata(self):
        print """\
<?xml version="1.0"?>
<!DOCTYPE resource-agent SYSTEM "ra-api-1.dtd">
<resource-agent name="pgsql">
    <version>1.0</version>

    <longdesc lang="en">
    ZEO Server Resource Agent.
    </longdesc>
    <shortdesc lang="en">zeo</shortdesc>

    <parameters>
        <parameter name="zeoctl" unique="0" required="0">
            <longdesc lang="en">Path to zeoctl script.</longdesc>
            <shortdesc lang="en">zeoctl</shortdesc>
            <content type="string" default="{zeoctl}" />
        </parameter>
        <parameter name="zeosock" unique="0" required="0">
            <longdesc lang="en">Path to unix socket for ZEO server.</longdesc>
            <shortdesc lang="en">zeosock</shortdesc>
            <content type="string" default="{zeosock}" />
        </parameter>
        <parameter name="zeouser" unique="0" required="0">
            <longdesc lang="en">User that runs the ZEO server.</longdesc>
            <shortdesc lang="en">zeouser</shortdesc>
            <content type="string" default="{zeouser}" />
        </parameter>
    </parameters>

    <actions>
        <action name="start" timeout="30" />
        <action name="stop" timeout="30" />
        <action name="status" timeout="10" />
        <action name="monitor" depth="0" timeout="10" interval="30"/>
        <action name="meta-data" timeout="5" />
        <action name="methods" timeout="5" />
    </actions>
</resource-agent>""".format(**self.__dict__)
        return 0

    def status(self):
        if self._status() :
            print >>sys.stderr, "Zeo is up"
        else:
            print >>sys.stderr, "Zeo is down"
        return 0

    def methods(self):
        print '\n'.join(self._actions.keys())

    def __call__(self, a):
        logger.info("Calling action %s on %s", a, self.resourcename)
        action = self._actions.get(a, None)
        assert action is not None, "Invalid method"
        result = action()
        logger.info("result: %d", result)
        return result


def main():
    agent = ResourceAgent()
    sys.exit(agent(sys.argv[1]))

if __name__ == '__main__':
    main()
