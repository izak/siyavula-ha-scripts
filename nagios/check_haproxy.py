#!/usr/bin/python
#
# Python nagios plugin to check an haproxy status page and ensure that all is
# well.

import sys
import argparse
import urllib2
import csv
from collections import defaultdict

GOOD = 0
WARNING = 1
CRITICAL = 2

status_text = {
    GOOD: 'OK',
    WARNING: 'WARNING',
    CRITICAL: 'CRITICAL'
}

class Status(object):
    def __init__(self, warning, critical):
        self.warning = warning
        self.critical = critical
        self.name = None
        self.backends = 0
        self.healthy = 0
        self.up = False

    @property
    def status(self):
        if self.up and self.backends > 0:
            p = (float(self.healthy)*100)/self.backends
            if p < self.critical:
                return CRITICAL
            if p < self.warning:
                return WARNING
            return GOOD
        return CRITICAL

    def __repr__(self):
        return '{}: {} {}/{}'.format(
            self.name, status_text[self.status], self.healthy, self.backends)

def get_csv(url):
    req = urllib2.Request(url + ';csv')
    response = urllib2.urlopen(req)
    if response.code == 200:
        return response
    return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--url", help="Haproxy status url")
    parser.add_argument("-w", "--warning", type=int,
        help="Warning level as percentage of dead backends", default=25)
    parser.add_argument("-c", "--critical", type=int,
        help="Critical level as percentage of dead backends", default=50)
    args = parser.parse_args()
    if not args.url:
        parser.error('You must provide a haproxy status url')

    response = get_csv(args.url)
    data = defaultdict(lambda: Status(args.warning, args.critical))
    if response is not None:
        for row in csv.reader(response):
            assert len(row) > 17, "Malformed row in csv response"
            if row[0].startswith('#'): continue # Skip headings
            pxname = row[0]
            svname = row[1]
            status = row[17]

            data[pxname].name = pxname
            if svname == 'BACKEND' and status == 'UP':
                data[pxname].up = True
            elif svname not in ('FRONTEND', 'BACKEND'):
                data[pxname].backends += 1
                if status == 'UP': data[pxname].healthy += 1

        if len(data) == 0:
            sys.exit(3) # Unknown

        # Overal status
        status = max([s.status for s in data.values()])
        print ', '.join([str(s) for s in data.values()])
        sys.exit(status)

    print "Couldn't figure out haproxy output"
    sys.exit(3) # Unknown

if __name__ == '__main__':
    main()
