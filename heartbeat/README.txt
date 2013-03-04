Resource agent for postgresql
=============================

There is already a resource agent for postgresql, written by Takatoshi MATSUO.
I had some trouble getting it going, and in an effort to simplify things and
perhaps understand them, I ended up writing my own.

This RA assumes you have only two nodes, the way many people will be running
it. It makes live somewhat easier. It also does not monitor the exact state
of each instance. For this you really should use another monitoring system,
such as nagios and/or munin.

Step 1: Set up postgresql replication
-------------------------------------

This is not a complete list of steps on how to set up replication. There are
plenty of others available on the internet. Specifically, you need to
configure replication users in pg_hba.conf and that is not discussed here.

On both nodes, create an ha cluster:

  pg_createcluster 9.1 ha

Change these settings in postgresql.confS on both nodes:

  wal_level = hot_standby
  max_wal_senders = 5
  hot_standby = on
  archive_mode = on
  archive_command = 'cp %p /var/lib/postgresql/9.1/replica2/_archive/%f'
  archive_command = 'scp -P 222 %p node2:/var/lib/postgresql/archive/9.1/ha/%f'

Replace node2 with the name of the _other_ node, so that each instance will
make copies of its WAL files to the other node.

Step 2: Initial replication to second node
------------------------------------------

Start up the cluster on node1. Load your data on node1 (or just create an empty
database) in the ha cluster.

Then, on the second node (without starting the cluster), use pg_basebackup to
get a copy.

  su - postgres
  cd /var/lib/postgresql/9.1
  mkdir ha.new
  chmod 700 ha.new
  /usr/lib/postgresql/9.1/bin/pg_basebackup -h 10.0.0.11 -p 5435 -D ha.new
  ln -s /etc/ssl/certs/ssl-cert-snakeoil.pem ha.new/server.crt
  ln -s /etc/ssl/private/ssl-cert-snakeoil.key ha.new/server.key
  mv ha ha.old && mv ha.new ha

The above steps takes extra care to preserve the old data directory as ha.old.
Delete it once you're done. Note that 10.0.0.11 is the ip address of your
first node, and that you already need to have pg_hba.conf configured on that
node so that replication is allowed from the second node.

Finally, stop the cluster on node1. It will be started by pacemaker later.

Step 3: SSH keys on both nodes
------------------------------

This is needed for copying WAL files between nodes. So on both nodes, generate
a key and place it in $HOME/.ssh/authorized_keys on the other node:

  su - postgres
  ssh-keygen -t rsa

Accept the defaults and don't specify a passphrase. Copy the content of
.ssh/id_rsa.pub to .ssh/authorized_keys on the other node. Finally, as the
postgres user, ssh from each node to the other and accept the host key.

Step 4: Tell the OS not to start these instances
------------------------------------------------

Edit /etc/postgresql/9.1/ha/start.conf and replace "auto" with "manual".

Step 5: Configure Heartbeat
----------------------------

Once again, this is not a full discussion on how to set up heartbeat. I assume
you have heartbeat 3.0.x or later running, with pacemaker 1.1.x or later.

I also assume that 10.0.0.1 can be used as a floating ip address. On either
node, run the command:

  crm configure

This will start the crm shell, in configure mode. Cut and paste this into
the shell:

  primitive psqlip ocf:heartbeat:IPaddr2 \
    params ip="10.0.0.1" cidr_netmask="24" nic="eth0" \
        op monitor interval="30s"

  primitive psql ocf:upfront:pgsql params \
    primary="host=10.0.0.1 port=5435 user=postgres" \
    version="9.1" clustername="ha" \
    port="5435" datadir="/var/lib/postgresql/9.1/ha" \
    restorecommand="cp /var/lib/postgresql/archive/9.1/ha/%f %p"
    op start   timeout="3600s" on-fail="stop" \
    op demote  timeout="600s" interval="30s" on-fail="stop" \
    op stop    timeout="60s" on-fail="block" \
    op monitor timeout="29s" interval="30s" on-fail="restart" \
    op monitor timeout="28s" interval="29s" on-fail="restart" role="Master"

  ms mspsql psql \
    meta \
    master-max="1" \
    master-node-max="1" \
    clone-max="2" \
    clone-node-max="1" \
    notify="true"

  order psqlip-before-mspsql \
    mandatory: mspsql:start mspsql:promote

  colocation psql-on-psqlip inf: psqlip mspsql:Master

  location psql-master-node mspsql rule \
    role=master 100: \#uname eq node1

  commit

After a while, heartbeat should start up both postgresql instances, and promote
the one on node1 to primary. You can check using either of these commands:

  crm_mon -1 -fA
  crm resource status

Step 6. Test failover
---------------------

Run the command:

  crm configure edit

Change the location rule psql-master-node so that node2 is preferred. Once
again wait a few seconds while the service migrates, using the above commands
to monitor.
