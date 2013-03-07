#!/usr/bin/python
#
# This needs python-argparse, if used with python2.6.
#
# This plugin simply checks /proc/drbd to ensure the drbd resources are
# up to date.

import sys
import os
import re

R = re.compile(' ([0-9]+): cs:([^ ]+) ro:([^ ]+) ds:([^ ]+)')

def main():
    if not os.path.exists('/proc/drbd'):
        print "DRBD not installed"
        sys.exit(3)

    fp = open('/proc/drbd')
    devices = []
    for line in fp:
        m = R.match(line)
        if m is None:
            continue

        device, cs, ro, ds = m.groups()
        if cs != 'Connected':
            print "Device %s is unconnected" % device
            sys.exit(2)
        if ds != 'UpToDate/UpToDate':
            print "Device %s is out of date (%s)" % (device, ds)
            sys.exit(2)

        devices.append(device)
    fp.close()
    print "DRBD devices [%s] OK" % ", ".join(devices)
    sys.exit(0)

if __name__ == "__main__":
    main()
