#!/usr/bin/python
#
# Resource agent for a zope zeo server.
#
#  primitive zeo ocf:upfront:zeo \
#    op start   timeout="3600s" on-fail="stop" \
#    op demote  timeout="60s" interval="30s" on-fail="stop" \
#    op stop    timeout="60s" on-fail="block" \
#    op monitor timeout="29s" interval="30s" on-fail="restart" \
#    op monitor timeout="28s" interval="29s" on-fail="restart" role="Master"


import sys
import socket
import os
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

def check_tcp(address, port):
    s = socket.socket()
    try:
        s.connect((address, port))
        s.close()
        return True
    except socket.error, e:
        pass
    return False

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
        self.zeohost = os.environ.get('OCF_RESKEY_zeohost', '127.0.0.1')
        self.zeoport = int(os.environ.get('OCF_RESKEY_zeoport', '8100'))

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
        return check_tcp(self.zeohost, self.zeoport)

    def start(self):
        if not self._status():
            return self._zeoctl('start')
        return 0

    def stop(self):
        if self._status():
            self._zeoctl('stop')
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
        <parameter name="zeohost" unique="0" required="0">
            <longdesc lang="en">Hostname of ZEO server.</longdesc>
            <shortdesc lang="en">zeohost</shortdesc>
            <content type="string" default="{zeohost}" />
        </parameter>
        <parameter name="zeoport" unique="0" required="0">
            <longdesc lang="en">TCP port for ZEO server.</longdesc>
            <shortdesc lang="en">zeoport</shortdesc>
            <content type="string" default="{zeoport}" />
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
