#!/usr/bin/python
#
# This is a (hopefully simple) resource agent for managing a postgresql cluster
# in binary streaming mode.

import sys
import os
from time import sleep
import pickle
import pwd
import subprocess
import shlex
import syslog
import socket
from ctypes import cdll
import logging
import psycopg2

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

# This here for debugging only
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

class DataObject(object):
    """ An object holding data on its attributes. """
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

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
            'methods': self.methods
        }
        self.settings = self._settings()

    def _settings(self):
        # TODO: Sync these with metadata xml
        return DataObject(
            hostname = socket.gethostname(),
            resourcename = os.environ.get('OCF_RESOURCE_INSTANCE',
                ''),
            pgctlcluster = os.environ.get('OCF_RESKEY_pgctlcluster',
                '/usr/bin/pg_ctlcluster'),
            version = os.environ.get('OCF_RESKEY_version', '9.1'),
            clustername = os.environ.get('OCF_RESKEY_clustername', 'main'),
            port = int(os.environ.get('OCF_RESKEY_port', '5432')),
            user = os.environ.get('OCF_RESKEY_user', 'postgres'),
            primary = os.environ.get('OCF_RESKEY_primary', 'host=127.0.0.1 port=5431 user=postgres'),
            restorecommand = os.environ.get('OCF_RESKEY_restorecommand', None),
            database = os.environ.get('OCF_RESKEY_database', 'template1'),
            datadir = os.environ.get('OCF_RESKEY_datadir', '/var/lib/postgresql/9.1/main'),
            sbindir = os.environ.get('OCF_RESKEY_sbindir', '/usr/sbin'),
        )

    def make_recovery(self):
        @fork_and_exec
        @drop_privileges(self.settings.user)
        def _make_recovery():
            fp = open(os.path.join(self.settings.datadir, 'recovery.conf'), 'w')
            fp.write("standby_mode = 'on'\n"
                "primary_conninfo = '%s'\n"
                "recovery_target_timeline = 'latest'\n"
                "trigger_file = '%s'\n" % (
                self.settings.primary,
                os.path.join(self.settings.datadir, '_trigger')))
            if self.settings.restorecommand is not None:
                fp.write("restore_command = '%s'\n" % \
                    self.settings.restorecommand)
            fp.close()
        return _make_recovery()

    def _ctlcluster(self, action, options=None):
        cmd = "%s '%s' '%s' %s" % (
            self.settings.pgctlcluster,
            self.settings.version,
            self.settings.clustername, action)
        if options is not None:
            # pg_ctl options
            cmd += ' -- ' + options
        logger.info("calling %s", cmd)
        try:
            sh(cmd)
        except CommandFailed:
            logger.info("error")
            return 1
        logger.info("returning")
        return 0

    def start(self):
        if self._status() > 0:
            # Already started
            return 0

        # postgresql must be started in slave mode, that is, it needs to drop
        # a recovery.conf file first
        self.make_recovery()
        return self._ctlcluster('start', options='-w')

    def stop(self):
        if self._status()==0:
            return 0
        return self._ctlcluster('stop', options='-m fast')

    def monitor(self):
        # Before we do anything else, check if postgres is even running
        # using a cheap check. On most setups the PID file is in /var/run,
        # and in most modern setups that would be on an in-memory tmpfs,
        # so doing a check on that should be cheap.
        if not os.path.exists(os.path.join('/var/run/postgresql', '%s-%s.pid' % (
                self.settings.version, self.settings.clustername))):

            # It's either not installed, or not running. If the data dir
            # is not on this machine, assume it is not installed
            if os.path.exists(self.settings.datadir):
                # Not running
                return 7
            else:
                return 5

        status = self._status()
        if status == 2:
            return 8
        elif status > 0:
            return 0
        return 7

    def metadata(self):
        print """\
<?xml version="1.0"?>
<!DOCTYPE resource-agent SYSTEM "ra-api-1.dtd">
<resource-agent name="pgsql">
    <version>1.0</version>

    <longdesc lang="en">
    Resource agent to manage PostgreSQL as an HA resource.
    </longdesc>
    <shortdesc lang="en">Manages a PostgreSQL database cluster</shortdesc>

    <parameters>
        <parameter name="pgctlcluster" unique="0" required="0">
            <longdesc lang="en">Path to pg_ctlcluster command.</longdesc>
            <shortdesc lang="en">pg_ctlcluster</shortdesc>
            <content type="string" default="{pgctlcluster}" />
        </parameter>
        <parameter name="version" unique="0" required="0">
            <longdesc lang="en">Postgresql version of this cluster.</longdesc>
            <shortdesc lang="en">version</shortdesc>
            <content type="string" default="{version}" />
        </parameter>
        <parameter name="clustername" unique="0" required="0">
            <longdesc lang="en">Name of cluster.</longdesc>
            <shortdesc lang="en">clustername</shortdesc>
            <content type="string" default="{clustername}" />
        </parameter>
        <parameter name="port" unique="0" required="0">
            <longdesc lang="en">Port number user by cluster.</longdesc>
            <shortdesc lang="en">port</shortdesc>
            <content type="string" default="{port}" />
        </parameter>
        <parameter name="user" unique="0" required="0">
            <longdesc lang="en">User name running the cluster.</longdesc>
            <shortdesc lang="en">user</shortdesc>
            <content type="string" default="{user}" />
        </parameter>
        <parameter name="primary" unique="0" required="0">
            <longdesc lang="en">Connection details to primary server.</longdesc>
            <shortdesc lang="en">primary_conninfo</shortdesc>
            <content type="string" default="{primary}" />
        </parameter>
        <parameter name="restorecommand" unique="0" required="0">
            <longdesc lang="en">Command to restore WAL archive.</longdesc>
            <shortdesc lang="en">restorecommand</shortdesc>
            <content type="string" default="" />
        </parameter>
        <parameter name="database" unique="0" required="0">
            <longdesc lang="en">Name of database for monitoring connections.</longdesc>
            <shortdesc lang="en">database</shortdesc>
            <content type="string" default="{database}" />
        </parameter>
        <parameter name="datadir" unique="0" required="0">
            <longdesc lang="en">Directory where data for this cluster is stored.</longdesc>
            <shortdesc lang="en">datadir</shortdesc>
            <content type="string" default="{datadir}" />
        </parameter>
        <parameter name="sbindir" unique="0" required="0">
            <longdesc lang="en">Directory where cluster utilities are stored.</longdesc>
            <shortdesc lang="en">sbindir</shortdesc>
            <content type="string" default="{sbindir}" />
        </parameter>
    </parameters>

    <actions>
        <action name="start" timeout="30" />
        <action name="stop" timeout="30" />
        <action name="status" timeout="10" />
        <action name="monitor" depth="0" timeout="10" interval="30"/>
        <action name="monitor" depth="0" timeout="10" interval="29" role="Master" />
        <action name="promote" timeout="60" />
        <action name="demote" timeout="90" />
        <action name="meta-data" timeout="5" />
        <action name="methods" timeout="5" />
    </actions>
</resource-agent>""".format(**self.settings.__dict__)
        return 0

    def promote(self):
        @fork_and_exec
        @drop_privileges(self.settings.user)
        def _promote():
            open(os.path.join(self.settings.datadir, '_trigger'), 'w').close()
        logger.info("Starting promotion")
        _promote()
        while True:
            logger.info("Waiting for master mode")
            sleep(1) # Give postgresql a change to promote
            status = self._status()
            if status == 2:
                # master
                logger.info("Server is in master mode, promotion complete")
                return 0
            elif status == 0:
                # Postgresql is dead
                break
        logger.info("Server died, bailing")
        return 7

    def demote(self):
        logger.info("Making recovery.conf file")
        self.make_recovery()

        self._ctlcluster('stop', options='-m fast')
        self._ctlcluster('start', options='-w')

        if self._status() > 0:
            # master
            logger.info("Server is up, demotion complete")
            return 0

        logger.info("Server died, bailing")
        return 7

    def _status(self):
        @fork_and_exec
        @drop_privileges(self.settings.user)
        def __status():
            try:
                db = psycopg2.connect("port=%d dbname=%s" % (
                    self.settings.port, self.settings.database))
                cursor = db.cursor()
                cursor.execute("select pg_is_in_recovery()")
                if cursor.fetchone()[0]:
                    return 1 # slave
                else:
                    return 2 # master
            except psycopg2.OperationalError:
                pass
            return 0
        return __status()
        
    def status(self):
        if self._status() > 0:
            print >>sys.stderr, "Postgresql is up"
        else:
            print >>sys.stderr, "Postgresql is down"
        return 0

    def methods(self):
        print '\n'.join(self._actions.keys())

    def __call__(self, a):
        logger.info("Calling action %s on %s", a, self.settings.resourcename)
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
