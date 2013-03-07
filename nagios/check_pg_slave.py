#!/usr/bin/python
#
# Python munin plugin to check how far behind a postgresql replica might be.

import sys
import argparse
import psycopg2

def CalculateNumericalOffset(stringofs):
    pieces = stringofs.split('/')
    assert(len(pieces)==2)
    return 0xffffffff * int(pieces[0], 16) + int(pieces[1], 16)

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument('-d', '--dsn', action='append',
        help="DSN for a postgresql node",
        required=True)
    args = parser.parse_args()

    masterdata = []
    slavedata = []
    for dsn in args.dsn:
        db = psycopg2.connect(dsn)
        c = db.cursor()
        c.execute("select pg_is_in_recovery(), inet_server_addr()")
        if c.fetchone()[0]:
            c.execute("SELECT pg_last_xlog_receive_location(),pg_last_xlog_replay_location(),inet_server_addr()")
            slavedata.append(c.fetchone())
        else:
            c.execute("SELECT pg_current_xlog_location()")
            masterdata.append(c.fetchone())
        db.close()

    if len(masterdata) > 1:
        print "Multiple masters, potential split brain!"
        sys.exit(2)

    if len(masterdata) == 0:
        print "No master server"
        sys.exit(2)

    if len(slavedata) == 0:
        print "No slave servers to compare"
        sys.exit(3)

    master_num = CalculateNumericalOffset(masterdata[0][0])
    for slave in slavedata:
        receive_delay = master_num - CalculateNumericalOffset(slave[0])
        replay_delay = master_num = CalculateNumericalOffset(slave[1])
        if receive_delay > 0:
            print "%s is behind by %d" % (slave[2] or "localhost",
                receive_delay)
            sys.exit(2)

    print "Slaves OK"
    sys.exit(0)


if __name__ == '__main__':
    main()
