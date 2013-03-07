#!/usr/bin/python
#
# Python nagios plugin to check if there is a master postgresql server on
# host. Meant to be used with a floating ip address and high availability,
# which is why it only implements connecting by tcp with user/password.

import sys
import argparse
import psycopg2

def status(host, port, db, user, password):
    """ This does a check by connecting to the host via tcp. """
    try:
        db = psycopg2.connect("host=%s port=%d dbname=%s user=%s password=%s" % (
            host, port, db, user, password))
        cursor = db.cursor()
        cursor.execute("select pg_is_in_recovery()")
        if cursor.fetchone()[0]:
            print "Server is in recovery (slave)"
            return 2 # Error, it is a slave
        else:
            print "Server is not in recovery (master)"
            return 0 # master
    except psycopg2.OperationalError, e:
        print str(e)
    return 3 # Unknown

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int,
        help="Port for postgresql instance", default=5432)
    parser.add_argument("-H", "--host",
        help="Host for postgresql instance", default='localhost')
    parser.add_argument("-d", "--database",
        help="Database to connect to", default='template1')
    parser.add_argument("-u", "--user",
        help="Username for connection")
    parser.add_argument("-P", "--password",
        help="Password for connection", default='localhost')

    args = parser.parse_args()

    if not (args.user and args.password):
        parser.error('You must provide a user and password for the connection')

    sys.exit(status(args.host, args.port, args.database, args.user,
        args.password))


if __name__ == '__main__':
    main()
