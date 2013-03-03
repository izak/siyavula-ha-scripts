TODO:
1. Document postgresql.conf changes
2. Set up cross-server WAL archiving (ssh keys, scp)
3. First setup (copy database using pg_basebackup

Configuration primitives

crm configure
  primitive psqlip ocf:heartbeat:IPaddr2 \
    params ip="10.0.0.1" cidr_netmask="24" nic="eth0" \
        op monitor interval="30s"

  primitive monassispsql ocf:upfront:pgsql params \
    primary="host=10.0.0.1 port=5435 user=postgres" \
    version="9.1" clustername="monassisha" \
    port="5435" datadir="/var/lib/postgresql/9.1/monassisha" \
    restorecommand="cp /var/lib/postgresql/archive/9.1/monassisha/%f %p"
    op start   timeout="3600s" on-fail="stop" \
    op demote  timeout="600s" interval="30s" on-fail="stop" \
    op stop    timeout="60s" on-fail="block" \
    op monitor timeout="29s" interval="30s" on-fail="restart" \
    op monitor timeout="28s" interval="29s" on-fail="restart" role="Master"

  ms msmonassispsql monassispsql \
    meta \
    master-max="1" \
    master-node-max="1" \
    clone-max="2" \
    clone-node-max="1" \
    notify="true"

  order psqlip-before-msmonassispsql \
    mandatory: msmonassispsql:start msmonassispsql:promote

  colocation monassispsql-on-psqlip inf: psqlip msmonassispsql:Master

  location psql-master-s3 msmonassispsql rule \
    role=master 100: \#uname eq server3

  commit

