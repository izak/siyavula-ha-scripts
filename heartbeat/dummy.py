#!/usr/bin/python
#
# Dummy resource agent. Does nothing, just pretend to go up and down when
# told to do so. This can serve as an example of how to write a resource
# agent in python, if you need a dummy service for whatever reason, or
# just to figure out how things work.
#
#  primitive dummy ocf:upfront:dummy \
#    op start   timeout="3600s" on-fail="stop" \
#    op demote  timeout="60s" interval="30s" on-fail="stop" \
#    op stop    timeout="60s" on-fail="block" \
#    op monitor timeout="29s" interval="30s" on-fail="restart" \
#    op monitor timeout="28s" interval="29s" on-fail="restart" role="Master"
#
#  ms msdummy dummy \
#    meta \
#    master-max="1" \
#    master-node-max="1" \
#    clone-max="2" \
#    clone-node-max="1" \
#    notify="true"
#
#  order psqlip-before-dummy \
#    mandatory: dummy:start dummy:promote
#
#  colocation dummy-on-psqlip inf: psqlip dummy:Master
#
#  location dummy-on-s3 msdummy rule role=master 100: \#uname eq server3



import sys
import os
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
logger.addHandler(logging.FileHandler('/tmp/halog'))
logger.setLevel(logging.INFO)

class ResourceAgent(object):
    def __init__(self):
        self._actions = {
            'start': self.start,
            'stop': self.stop,
            'status': self.status,
            'monitor': self.monitor,
            'meta-data': self.metadata,
            'promote': self.promote,
            'demote': self.demote,
            'notify': self.notify,
            'methods': self.methods
        }
        self.resourcename = os.environ.get('OCF_RESOURCE_INSTANCE', 'dummy')


    @property
    def _status(self):
        service = self.resourcename.split(':')[0]
        fn = os.path.join('/tmp', service)
        if os.path.exists(fn):
            fp = open(fn, 'r')
            if fp.read().startswith('2'):
                return 2 # master
            else:
                return 1 # slave
        else:
            return 0 # not running

    def start(self):
        if self._status == 0:
            service = self.resourcename.split(':')[0]
            fn = os.path.join('/tmp', service)
            fp = open(fn, 'w')
            fp.write('1')
            fp.close()
        return 0

    def stop(self):
        service = self.resourcename.split(':')[0]
        fn = os.path.join('/tmp', service)
        os.unlink(fn)
        return 0

    def monitor(self):
        if self._status > 1:
            return 8
        if self._status == 1:
            return 0
        return 7

    def metadata(self):
        print """\
<?xml version="1.0"?>
<!DOCTYPE resource-agent SYSTEM "ra-api-1.dtd">
<resource-agent name="pgsql">
    <version>1.0</version>

    <longdesc lang="en">
    Dummy Resource Agent.
    </longdesc>
    <shortdesc lang="en">dummy</shortdesc>

    <parameters>
    </parameters>

    <actions>
        <action name="start" timeout="30" />
        <action name="stop" timeout="30" />
        <action name="status" timeout="10" />
        <action name="monitor" depth="0" timeout="10" interval="30"/>
        <action name="monitor" depth="0" timeout="10" interval="29" role="Master" />
        <action name="promote" timeout="60" />
        <action name="demote" timeout="60" />
        <action name="notify" timeout="45" />
        <action name="meta-data" timeout="5" />
        <action name="methods" timeout="5" />
    </actions>
</resource-agent>"""
        return 0

    def promote(self):
        if self._status == 0:
            return 7 # Not running

        service = self.resourcename.split(':')[0]
        fn = os.path.join('/tmp', service)
        fp = open(fn, 'w')
        fp.write('2')
        fp.close()
        return 0

    def demote(self):
        if self._status == 0:
            return 7 # Not running

        service = self.resourcename.split(':')[0]
        fn = os.path.join('/tmp', service)
        fp = open(fn, 'w')
        fp.write('1')
        fp.close()

        return 0

    def notify(self):
        try:
            t = os.environ['OCF_RESKEY_CRM_meta_notify_type']
            o = os.environ['OCF_RESKEY_CRM_meta_notify_operation']

            if o == "promote":
                master = os.environ['OCF_RESKEY_CRM_meta_notify_master_uname']
                promote = os.environ['OCF_RESKEY_CRM_meta_notify_promote_uname']
                logger.info("Current master is %s", master)
                logger.info("%s-promotion event for %s", t, promote)

            elif o == "demote":
                master = os.environ['OCF_RESKEY_CRM_meta_notify_master_uname']
                demote = os.environ['OCF_RESKEY_CRM_meta_notify_demote_uname']
                logger.info("Current master is %s", master)
                logger.info("%s-demotion event for %s", t, demote)

            else:
                logger.info("%s-%s event", t, o)
        except Exception, e:
            logger.info(e)

        return 0

    def status(self):
        if self._status > 0:
            print >>sys.stderr, "Dummy is up"
        else:
            print >>sys.stderr, "Dummy is down"
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
