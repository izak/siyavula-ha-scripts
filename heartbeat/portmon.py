#!/usr/bin/python
#
# Port monitor resource agent. Similar to ping, except it assigns a score
# depending on reachable ports. Written because varnish has this bad habbit
# of losing a port without falling over entirely.
#
#  primitive porthealth ocf:upfront:portmon \
#    params name="varnish" portlist="localhost:80 localhost:443" \
#    op monitor interval="60s" timeout="30s" on-fail="stop"
#
#

import sys
import os
import subprocess, shlex
import socket

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

def checkport(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect((host, port))
        s.shutdown(2)
        return True
    except:
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
        self.resourcename = os.environ.get('OCF_RESKEY_name', 'portmon')
        varrun = os.environ.get('HA_VARRUN', '/var/run')
        self.pidfile = os.path.join(varrun, 'portmon-%s' % self.resourcename)
        self.portlist = [tuple(h.split(':')) for h in 
            os.environ.get('OCF_RESKEY_portlist', '').split()]

    @property
    def _status(self):
        return os.path.exists(self.pidfile)

    def start(self):
        if not self._status:
            open(self.pidfile, 'w').close()
        return 0

    def stop(self):
        os.unlink(self.pidfile)
        sh("/usr/sbin/attrd_updater -D -n '%s' -d 5 -q" % self.resourcename)
        return 0

    def monitor(self):
        if self._status:
            count = sum([int(checkport(h, int(p))) for h, p in self.portlist])

            # Attempt to update the attribute
            try:
                if count > 0:
                    sh("/usr/sbin/attrd_updater -n '%s' -v %d -d 5 -q" % (
                        self.resourcename, count))
                else:
                    sh("/usr/sbin/attrd_updater -D -n '%s' -d 5 -q" % (
                        self.resourcename,))
            except CommandFailed:
                pass
            return 0
        return 7

    def metadata(self):
        print """\
<?xml version="1.0"?>
<!DOCTYPE resource-agent SYSTEM "ra-api-1.dtd">
<resource-agent name="pgsql">
    <version>1.0</version>

    <longdesc lang="en">
    This is similar to the ping ra, except that it checks if ports are open
    and assigns a score based on how many ports are reachable.
    </longdesc>
    <shortdesc lang="en">portmon</shortdesc>

    <parameters>
        <parameter name="name" unique="0" required="0">
            <longdesc lang="en">Name representing group of monitored ports</longdesc>
            <shortdesc lang="en">name</shortdesc>
            <content type="string" default="portmon" />
        </parameter>
        <parameter name="portlist" unique="0" required="0">
            <longdesc lang="en">Space delimited list of host:port pairs to monitor</longdesc>
            <shortdesc lang="en">name</shortdesc>
            <content type="string" default="" />
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
</resource-agent>"""
        return 0

    def status(self):
        if self._status:
            print >>sys.stderr, "%s is up" % self.resourcename
        else:
            print >>sys.stderr, "%s is down" % self.resourcename
        return 0

    def methods(self):
        print '\n'.join(self._actions.keys())

    def __call__(self, a):
        action = self._actions.get(a, None)
        assert action is not None, "Invalid method"
        result = action()
        return result


def main():
    agent = ResourceAgent()
    sys.exit(agent(sys.argv[1]))

if __name__ == '__main__':
    main()
