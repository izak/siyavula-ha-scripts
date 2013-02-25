#!/usr/bin/python
#
# This needs nagios-plugins to be installed. It also needs python-argparse, if
# used with python2.6.
#
# This is a simple disk space plugin, except that file systems that are not
# mounted are deemed to be OK - They are mounted somewhere else.

import sys
import os
import statvfs
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-w", "--warning", type=int,
        help="Warning disk space percentage", default=90)
    parser.add_argument("-c", "--critical", type=int,
        help="Critical disk space percentage", default=95)
    parser.add_argument("filesystem", help="The filesystem to check")
    args = parser.parse_args()

    if os.path.ismount(args.filesystem):
        stats = os.statvfs(args.filesystem)
        blocks = stats.f_bfree * stats.f_frsize
        total = stats.f_blocks * stats.f_frsize
        assert total>0, "A file system with zero blocks? Surely you jest?"
        percentage = (blocks * 100) / total

        if percentage > args.critical:
            print "DISK CRITICAL - free space: %s %d%%" % (args.filesystem,
                percentage)
            sys.exit(2)
        elif percentage > args.warning:
            print "DISK WARNING - free space: %s %d%%" % (args.filesystem,
                percentage)
            sys.exit(1)
        else:
            print "DISK OK - free space: %s %d%%" % (args.filesystem,
                percentage)
            sys.exit(0)
    else:
        print "N/A - %s not mounted" % args.filesystem
        sys.exit(0)

if __name__ == "__main__":
    main()
