#!/usr/bin/python
#
# This needs python-argparse, if used with python2.6.
#
# This is a simple memory plugini that checks how much memory is used for
# caching. A linux host performs best if it has a healthy amount of memory
# allocated to caching, and when you squeeze out caching memory the host
# generally starts to thrash. This plugin checks for healthy amounts of cache.

import sys
import os
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-w", "--warning", type=float,
        help="Warning memory percentage", default=1.0)
    parser.add_argument("-c", "--critical", type=float,
        help="Critical memory percentage", default=0.5)
    args = parser.parse_args()

    total = None
    cache = None
    free = None
    fp = open('/proc/meminfo', 'r')
    for l in fp.readlines():
        if l.startswith('Cached:'):
            cache = [x.strip() for x in l.strip().split(':')][1]
        elif l.startswith('MemFree:'):
            free = [x.strip() for x in l.strip().split(':')][1]
        elif l.startswith('MemTotal:'):
            total = [x.strip() for x in l.strip().split(':')][1]

    if cache is None:
        print "Could not parse Cached from /proc/meminfo"
        sys.exit(3)
    if free is None:
        print "Could not parse MemFree from /proc/meminfo"
        sys.exit(3)
    if total is None:
        print "Could not parse MemTotal from /proc/meminfo"
        sys.exit(3)

    cache = int(cache.split()[0])
    free = int(free.split()[0])
    total = int(total.split()[0])

    pfree = (free * 100) / total
    pcache = (cache * 100) / total

    if max(pfree, pcache) < args.critical:
        print "CACHE CRITICAL - cached: %d%%, free: %d%%" % (pcache, pfree)
        sys.exit(2)
    elif max(pfree, pcache) < args.warning:
        print "CACHE WARNING - cached: %d%%, free: %d%%" % (pcache, pfree)
        sys.exit(1)
    else:
        print "CACHE OK - cached: %d%%, free: %d%%" % (pcache, pfree)
        sys.exit(0)

if __name__ == "__main__":
    main()
