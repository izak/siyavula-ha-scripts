#!/usr/bin/python
#
# Python munin plugin to check how far behind a postgresql replica might be.

import psycopg2

masterdsn = "dbname=template1 port=5432"
slavedsn = "host=172.16.1.2 port=5432 dbname=template1 user=monitor password=secret"

def CalculateNumericalOffset(stringofs):
    pieces = stringofs.split('/')
    assert(len(pieces)==2)
    return 0xffffffff * int(pieces[0], 16) + int(pieces[1], 16)

dbm = psycopg2.connect(masterdsn)
dbs = psycopg2.connect(slavedsn)
cm = dbm.cursor()
cm.execute("SELECT pg_current_xlog_location()")
masterdata = cm.fetchone()

cs = dbs.cursor()
cs.execute("SELECT pg_last_xlog_receive_location(),pg_last_xlog_replay_location()")
slavedata = cs.fetchone()


master_num = CalculateNumericalOffset(masterdata[0])
receive_delay = master_num - CalculateNumericalOffset(slavedata[0])
replay_delay = master_num = CalculateNumericalOffset(slavedata[1])

print "receive.value %d" % receive_delay
print "apply.value %d" % replay_delay
