from datetime import datetime
from prometheus_client import start_http_server
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, REGISTRY, UntypedMetricFamily, InfoMetricFamily
import argparse
import IfxPy
import os
import re
import sys
import time


class InformixCollector(object):
    
    connection = None
    connstr = ''
    # Version can be [11,12,14]
    version = 12
    # If empty, we'll try to figure it out ourselves
    dbhostname = ""
    # If empty, we'll try to figure it out ourselves
    ha_alias = ""
    # Bitshifting (<<) 30 times to go from GiB to bytes
    memory_matrix = { 11: {'DE': 1<<30,
                           'EE': 1<<30,
                           'IE': 2<<30,
                           'WE': 1<<30
                          },
                      12: {'DE': 1<<30,
                           'EE': 8<<30,
                           'IE': 2<<30,
                           'WE': 16<<30
                          },
                      14: {'DE': 16<<30,
                           'EE': 8<<30,
                           'IE': 8<<30,
                           'WE': 32<<30
                          }
                    }
    sql_matrix = { 11: {'uptime_mode':             'SELECT (sh_curtime-sh_boottime) as online, sh_mode as mode FROM sysshmvals;',
                        'version':                 'SELECT FIRST 1 TRIM(version) as version FROM syslicenseinfo ORDER BY year,week DESC;',
                        'memory':                  'SELECT SUM(seg_size) as total_size FROM sysseglst;',
                        'sessions':                'SELECT TRIM(username) as user, TRIM(hostname) as host, COUNT(username) as count FROM syssessions GROUP BY 1,2;',
                        'config_changes':          'SELECT count(cf_id) as count FROM syscfgtab WHERE cf_effective != cf_original AND cf_original != \'\' AND cf_id not in (5,8,11,31,45,47,51,53,54,58,67,79,122,128,129,172,177,182,201,216,234,278,281,288,288,310,311);',
                        'dbspace_sizes':           'SELECT TRIM(sysdbspaces.name) as name, SUM(syschunks.chksize*sh_pagesize) as size, SUM(syschunks.nfree*sh_pagesize) as free FROM sysshmvals,syschunks JOIN sysdbspaces ON syschunks.dbsnum = sysdbspaces.dbsnum GROUP BY 1 ORDER BY NAME;',
                        'sysprofile':              'SELECT TRIM(name) as name, value FROM sysprofile;',
                        'vpu_class':               'SELECT TRIM(classname) as classname, SUM(usecs_user) as usecs_user, SUM(usecs_sys) as usecs_sys, SUM(readyqueue) as readyqueue, SUM(num_ready) as num_ready , CAST(COUNT(*) - SUM(num_ready) AS INT) idle, SUM(total_semops) semops, SUM(total_busy_wts) busy_waits, SUM(total_spins) spins FROM sysvplst GROUP BY classname;',
                        'open_transactions':       'SELECT COUNT(*) as open_transactions FROM systrans;',
                        'locks_per_user':          'SELECT TRIM(username) as username, SUM(nlocks) as locks FROM sysrstcb GROUP BY 1;',
                        'mutexes':                 'SELECT COUNT(*) as mutex_count FROM sysmutexes WHERE mtx_holder != 0;',
                        'threads':                 'SELECT TRIM(classname) as classname, th_state as threadstate, count(th_id) as count FROM systhreads JOIN sysvplst ON systhreads.th_vpid = sysvplst.vpid GROUP BY 1,2;',
                        'buffers':                 'SELECT SUM(bufsize*nbuffs) as size, SUM(dskreads) as dskreads, SUM(pagreads) as pagreads, SUM(bufreads) as bufreads, SUM(dskwrites) as dskwrites, SUM(pagwrites) as pagwrites, SUM(bufwrites) as bufwrites, SUM(bufwaits) as bufwaits, SUM(ovbuff) as ovbuff, SUM(flushes) as flushes, SUM(fgwrites) as fgwrites, SUM(lruwrites) as lruwrites, SUM(chunkwrites) as chunkwrites, SUM(lru_time_total) as lru_time_total, SUM(lru_calls) as lru_calls, ((pagreads + bufwrites) / nbuffs) as buffer_turnovers, bufsize as pagesize from sysbufpool GROUP BY 16,17;',
                        'slow_queries':            'SELECT COUNT(net_last_write) as slow_queries FROM sysnetworkio WHERE net_last_write-net_last_read>1;',
                        'rss_role':                'SELECT server_name FROM syssrcrss;',
                        'rss_info':                'SELECT TRIM(name) as name, TRIM(nodetype) as nodetype, TRIM(server_status) as server_status, TRIM(connection_status) as connection_status, delayed_apply as delayed_apply, TRIM(stop_apply) as stop_apply, (((logid_sent*3580)+logpage_sent) - ((logid_acked*3580)+logpage_acked)) as lag FROM syscluster;',
                        'rss_transmit_status':     'SELECT TRIM(server_name) as server_name, TRIM(log_transmission_status) as log_transmission_status FROM syssrcrss;',
                        'ha_alias':                'SELECT TRIM(cf_effective) as ha_alias FROM sysconfig WHERE cf_name = "HA_ALIAS";',
                        'hostname':                'SELECT TRIM(cf_default) as hostname FROM sysconfig WHERE cf_name = "DBSERVERNAME";',
                       },
                   12: {'uptime_mode':             'SELECT (sh_curtime-sh_boottime) as online, sh_mode as mode FROM sysshmvals;',
                        'version':                 'SELECT FIRST 1 TRIM(version) as version FROM syslicenseinfo ORDER BY year,week DESC;',
                        'memory':                  'SELECT SUM(seg_size) as total_size FROM sysseglst;',
                        'sessions':                'SELECT TRIM(username) as user, TRIM(hostname) as host, COUNT(username) as count FROM syssessions GROUP BY 1,2;',
                        'config_changes':          'SELECT count(cf_id) as count FROM syscfgtab WHERE cf_effective != cf_original AND cf_original != \'\' AND cf_id not in (5,8,11,31,45,47,51,53,54,58,67,79,122,128,129,172,177,182,201,216,234,278,281,288,288,310,311);',
                        'dbspace_sizes':           'SELECT TRIM(sysdbspaces.name) as name, SUM(syschunks.chksize*sh_pagesize) as size, SUM(syschunks.nfree*sh_pagesize) as free FROM sysshmvals,syschunks JOIN sysdbspaces ON syschunks.dbsnum = sysdbspaces.dbsnum GROUP BY 1 ORDER BY NAME;',
                        'sysprofile':              'SELECT TRIM(name) as name, value FROM sysprofile;',
                        'vpu_class':               'SELECT TRIM(classname) as classname, SUM(usecs_user) as usecs_user, SUM(usecs_sys) as usecs_sys, SUM(readyqueue) as readyqueue, SUM(num_ready) as num_ready , CAST(COUNT(*) - SUM(num_ready) AS INT) idle, SUM(total_semops) semops, SUM(total_busy_wts) busy_waits, SUM(total_spins) spins FROM sysvplst GROUP BY classname;',
                        'open_transactions':       'SELECT COUNT(*) as open_transactions FROM systrans;',
                        'locks_per_user':          'SELECT TRIM(username) as username, SUM(nlocks) as locks FROM sysrstcb GROUP BY 1;',
                        'mutexes':                 'SELECT COUNT(*) as mutex_count FROM sysmutexes WHERE mtx_holder != 0;',
                        'threads':                 'SELECT TRIM(classname) as classname, th_state as threadstate, count(th_id) as count FROM systhreads JOIN sysvplst ON systhreads.th_vpid = sysvplst.vpid GROUP BY 1,2;',
                        'buffers':                 'SELECT SUM(bufsize*nbuffs) as size, SUM(dskreads) as dskreads, SUM(pagreads) as pagreads, SUM(bufreads) as bufreads, SUM(dskwrites) as dskwrites, SUM(pagwrites) as pagwrites, SUM(bufwrites) as bufwrites, SUM(bufwaits) as bufwaits, SUM(ovbuff) as ovbuff, SUM(flushes) as flushes, SUM(fgwrites) as fgwrites, SUM(lruwrites) as lruwrites, SUM(chunkwrites) as chunkwrites, SUM(lru_time_total) as lru_time_total, SUM(lru_calls) as lru_calls, ((pagreads + bufwrites) / nbuffs) as buffer_turnovers, bufsize as pagesize from sysbufpool GROUP BY 16,17;',
                        'slow_queries':            'SELECT COUNT(net_last_write) as slow_queries FROM sysnetworkio WHERE net_last_write-net_last_read>1;',
                        'rss_role':                'SELECT server_name FROM syssrcrss;',
                        'rss_info':                'SELECT TRIM(name) as name, TRIM(nodetype) as nodetype, TRIM(server_status) as server_status, TRIM(connection_status) as connection_status, delayed_apply as delayed_apply, TRIM(stop_apply) as stop_apply, (((logid_sent*3580)+logpage_sent) - ((logid_acked*3580)+logpage_acked)) as lag FROM syscluster;',
                        'rss_transmit_status':     'SELECT TRIM(server_name) as server_name, TRIM(log_transmission_status) as log_transmission_status FROM syssrcrss;',
                        'ha_alias':                'SELECT TRIM(cf_effective) as ha_alias FROM sysconfig WHERE cf_name = "HA_ALIAS";',
                        'hostname':                'SELECT TRIM(cf_default) as hostname FROM sysconfig WHERE cf_name = "DBSERVERNAME";',
                       },
                   14: {'uptime_mode':             'SELECT (sh_curtime-sh_boottime) as online, sh_mode as mode FROM sysshmvals;',
                        'version':                 'SELECT FIRST 1 TRIM(version) as version FROM syslicenseinfo ORDER BY year,week DESC;',
                        'memory':                  'SELECT SUM(seg_size) as total_size FROM sysseglst;',
                        'sessions':                'SELECT TRIM(username) as user, TRIM(hostname) as host, COUNT(username) as count FROM syssessions GROUP BY 1,2;',
                        'config_changes':          'SELECT count(cf_id) as count FROM syscfgtab WHERE cf_effective != cf_original AND cf_original != \'\' AND cf_id not in (5,8,11,31,45,47,51,53,54,58,67,79,122,128,129,172,177,182,201,216,234,278,281,288,288,310,311);',
                        'dbspace_sizes':           'SELECT TRIM(sysdbspaces.name) as name, SUM(syschunks.chksize*sh_pagesize) as size, SUM(syschunks.nfree*sh_pagesize) as free FROM sysshmvals,syschunks JOIN sysdbspaces ON syschunks.dbsnum = sysdbspaces.dbsnum GROUP BY 1 ORDER BY NAME;',
                        'sysprofile':              'SELECT TRIM(name) as name, value FROM sysprofile;',
                        'vpu_class':               'SELECT TRIM(classname) as classname, SUM(usecs_user) as usecs_user, SUM(usecs_sys) as usecs_sys, SUM(readyqueue) as readyqueue, SUM(num_ready) as num_ready , CAST(COUNT(*) - SUM(num_ready) AS INT) idle, SUM(total_semops) semops, SUM(total_busy_wts) busy_waits, SUM(total_spins) spins FROM sysvplst GROUP BY classname;',
                        'open_transactions':       'SELECT COUNT(*) as open_transactions FROM systrans;',
                        'locks_per_user':          'SELECT TRIM(username) as username, SUM(nlocks) as locks FROM sysrstcb GROUP BY 1;',
                        'mutexes':                 'SELECT COUNT(*) as mutex_count FROM sysmutexes WHERE mtx_holder != 0;',
                        'threads':                 'SELECT TRIM(classname) as classname, th_state as threadstate, count(th_id) as count FROM systhreads JOIN sysvplst ON systhreads.th_vpid = sysvplst.vpid GROUP BY 1,2;',
                        'buffers':                 'SELECT SUM(bufsize*nbuffs) AS size, SUM(dskreads) AS dskreads, SUM(pagreads) AS pagreads, SUM(bufreads) AS bufreads, SUM(dskwrites) AS dskwrites, SUM(pagwrites) AS pagwrites, SUM(bufwrites) AS bufwrites, SUM(bufwaits) AS bufwaits, SUM(ovbuff) AS ovbuff, SUM(flushes) AS flushes, SUM(fgwrites) AS fgwrites, SUM(lruwrites) AS lruwrites, SUM(chunkwrites) AS chunkwrites, SUM(lru_time_total) AS lru_time_total, SUM(lru_calls) AS lru_calls, ((pagreads + bufwrites) / nbuffs) AS buffer_turnovers, bufsize AS pagesize from sysbufpool GROUP BY 16,17;',
                        'slow_queries':            'SELECT COUNT(net_last_write) as slow_queries FROM sysnetworkio WHERE net_last_write-net_last_read>1;',
                        'rss_role':                'SELECT server_name FROM syssrcrss;',
                        'rss_info':                'SELECT TRIM(name) as name, TRIM(nodetype) as nodetype, TRIM(server_status) as server_status, TRIM(connection_status) as connection_status, delayed_apply as delayed_apply, TRIM(stop_apply) as stop_apply, (((logid_sent*3580)+logpage_sent) - ((logid_acked*3580)+logpage_acked)) as lag FROM syscluster;',
                        'rss_transmit_status':     'SELECT TRIM(server_name) as server_name, TRIM(log_transmission_status) as log_transmission_status FROM syssrcrss;',
                        'ha_alias':                'SELECT TRIM(cf_effective) as ha_alias FROM sysconfig WHERE cf_name = "HA_ALIAS";',
                        'hostname':                'SELECT TRIM(cf_default) as hostname FROM sysconfig WHERE cf_name = "DBSERVERNAME";',
                       }
                 }
                     
    
    def __init__(_self, database, hostname, port, user, password):
        _self.connstr = "SERVER={0};DATABASE=sysmaster;HOST={1};SERVICE={2};UID={3};PWD={4};".format(database, hostname, port, user, password)
        sqlhostsfile = _self.write_sqlhosts_file(database, hostname, port)
        informixdir = '/opt/IBM/Informix_Client-SDK/'
        os.environ['INFORMIXDIR'] = informixdir
        os.environ['LD_LIBRARY_PATH'] = '{0}/lib/:{0}/lib/esql/:{0}/lib/cli/'.format(informixdir)
        os.environ['INFORMIXSQLHOSTS'] = sqlhostsfile
        os.environ['INFORMIXSERVER'] = database
        # Checking some configuration parameters
        if _self.version not in _self.sql_matrix.keys():
            raise Exception('Version not in SQL Matrix - bailing out.')
        _self.connect()
        # Setting some normally never changing values
        if _self.ha_alias == "":
            records = _self.execute_sql("ha_alias")
            if len(records) == 1:
                _self.ha_alias = records[0]['ha_alias']
        if _self.dbhostname == "":
            records = _self.execute_sql("hostname")
            if len(records) == 1:
                _self.dbhostname = records[0]['hostname']
        pass

    def print_help(_self):
        print "Usage: <scriptname>.py [OPTIONS]"
        print ""
        print "This script will connect to an IBM Informix and fetch monitoring data via the SQL interface. The result will"
        print "be spit out on a small HTTP server so you can use it as prometheus collector."
        print ""
        print "     -d  Name of the database instance. Eg: ol_informix1410"
        print "     -h  Show this help"
        print "     -H  Hostname or IP of your informix machine"
        print "     -p  Port of the database server"
        print "     -u  Username used to connect to the Informix instance"
        print "     -p  Password used to connect to the Informix instance"
        print ""
        print "Example:"
        print "python <scriptname>.py -d ol_informix1410 -H 192.168.56.101 -p 9098 -u informix -p informix"
        print ""

    def write_sqlhosts_file(_self, database, hostname, port):
        path = "/tmp/sqlhosts.{0}-{1}".format(hostname,database)
        try:
            sqlfile = open(path, 'w')
            sqlfile.write("{0} {1} {2} {3}".format(database, 'onsoctcp', hostname, port))
            sqlfile.close()
        except Exception, e:
            _self.print_error("Could not write sqlhosts file to ".format(path))
            _self.print_error(e)
            sys.exit(1)
        return path

    def print_info(_self, message):
        print "[II] {0} - {1}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)

    def print_error(_self, message):
        print "[EE] {0} - {1}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)

    def connect(_self):
        try:
            _self.connection = IfxPy.connect(_self.connstr, "", "")
        except Exception, e:
            _self.print_error("Could not connect to db with connection string:{0}".format(_self.connstr))
            _self.print_error(e)

    def disconnect(_self):
        try:
            IfxPy.close(_self.connection)
            _self.connection = None
        except Exception, e:
            _self.print_error("Could not disconnect")
            _self.print_error(e)

    def execute_sql(_self, sql_name):
        if sql_name not in _self.sql_matrix[_self.version].keys():
            raise Exception('{0} not in SQL Matrix for version {1} - bailing out.\n Please comment out the call using the sql statement in the collect() function.'.format(sql_name, _self.version))
        sql = _self.sql_matrix[_self.version][sql_name]
        try:
            stat = IfxPy.exec_immediate(_self.connection, sql)
        except Exception, e:
            _self.print_error("Could not execute SQL statement - are we connected? {0}".format(e))
            _self.disconnect()
            _self.connect()
            if not _self.connection is None:
                stat = IfxPy.exec_immediate(_self.connection, sql)
        if not _self.connection is None:
            res = IfxPy.fetch_assoc(stat)
        else:
            _self.print_error("Seems like we're not connected to the DB.")
            return
        records = []
        while res:
            row = {}
            for key in res.keys():
                row[key] = res[key]
            records.append(row)
            res = IfxPy.fetch_assoc(stat)
        IfxPy.free_result(stat)
        IfxPy.free_stmt (stat)
        return records
    
    def get_uptime_and_mode_info(_self):
        ifx_modes = {-1: 'Offline',
                      0: 'Initialisation',
                      1: 'Quiescent',
                      2: 'RSS secondary',
                      3: 'Backup',
                      4: 'Shutdown',
                      5: 'Online',
                      6: 'Abort'}
        uptime_gauge = GaugeMetricFamily('node_ifx_uptime', 'Uptime reported by informix', labels=["ifxserver"])
        ifx_mode = GaugeMetricFamily('node_ifx_mode', 'Informix current mode', labels=["ifxserver", "mode"])
        records = _self.execute_sql('uptime_mode')
        uptime_gauge.add_metric([_self.dbhostname], str(records[0]['online']))
        ifx_mode.add_metric([_self.dbhostname, ifx_modes[records[0]['mode']]], records[0]['mode'])
        return [uptime_gauge, ifx_mode]

    def get_max_license_memory_from_version(_self, version):
        matches = re.findall("^[0-9]*", version)
        if len(matches) != 1:
            # We didn't find the version, return 1GB
            return 1<<30
        major = int(matches[0])
        # If we were started with the wrong version or upgraded in the mean time
        if _self.version != major:
            _self.version = major
        edition = version[-2:]
        return _self.memory_matrix[major][edition]

    def get_memory_and_version_info(_self):
        metrics = []
        records = _self.execute_sql('version')
        if len(records) == 1:
            version = InfoMetricFamily('node_ifx_version', 'Informix version', labels=["ifxserver"])
            version.add_metric([_self.dbhostname], {'version': records[0]['version']})
            metrics.append(version)
            max_memory = GaugeMetricFamily('node_ifx_max_memory_allowed', 'Informix maximum allowed memory', labels=["ifxserver"])
            max_memory.add_metric([_self.dbhostname], _self.get_max_license_memory_from_version(records[0]['version']))
            metrics.append(max_memory)
        records = _self.execute_sql('memory')
        memory_used = GaugeMetricFamily('node_ifx_memory_used', 'Informix memory in use', labels=["ifxserver"])
        memory_used.add_metric([_self.dbhostname], records[0]['total_size'])
        metrics.append(memory_used)
        return metrics

    def get_session_info(_self):
        sessions = GaugeMetricFamily('node_ifx_sessions', 'Informix sessions', labels=['ifxserver', 'host', 'user'])
        records = _self.execute_sql('sessions')
        for record in records:
            if record['host'] == '':
                sessions.add_metric([_self.dbhostname, "SHMEM", record['user']], record['count'])
            else:
                sessions.add_metric([_self.dbhostname, record['host'], record['user']], record['count'])
        return sessions

    def get_config_changes(_self):
        config_changes = GaugeMetricFamily('node_ifx_config_changes', 'The number of config changes since startup', labels=["ifxserver"])
        records = _self.execute_sql('config_changes')
        config_changes.add_metric([_self.dbhostname], str(records[0]['count']))
        return config_changes

    def get_dbspaces_info(_self):
        # The SQL statement multiplies by 2 because the default page size is 2kB
        # The pagesize reported by Informix is used elsewhere
        dbspaces_free = GaugeMetricFamily('node_ifx_dbspaces_free_size', 'Free space in dbspaces in bytes', labels=["ifxserver", "dbspace"])
        dbspaces_size = GaugeMetricFamily('node_ifx_dbspaces_size', 'Size of dbspaces in bytes', labels=["ifxserver", "dbspace"])
        records = _self.execute_sql('dbspace_sizes')
        for record in records:
            dbspaces_free.add_metric([_self.dbhostname,record['name']], str(record['free']))
            dbspaces_size.add_metric([_self.dbhostname,record['name']], str(record['size']))
        return [dbspaces_free, dbspaces_size]

    def get_sysprofile_info(_self):
        records = _self.execute_sql('sysprofile')
        sysprofiles = []
        for record in records:
            sysprofile_info = CounterMetricFamily('node_ifx_sysprofile_{0}'.format(record['name']), 'Sysprofile value for {0}'.format(record['name']), labels=["ifxserver"])
            sysprofile_info.add_metric([_self.dbhostname], str(record['value']))
            sysprofiles.append(sysprofile_info)
        return sysprofiles

    def get_vpu_class_info(_self):
        records = _self.execute_sql('vpu_class')
        vpu_classes = []
        for record in records:
            class_info = CounterMetricFamily('node_ifx_vpu_class_{0}'.format(record['classname']), 'VPU info value for class {0}'.format(record['classname']), labels=["ifxserver", "class", "metric"])
            class_info.add_metric([_self.dbhostname, record['classname'], 'usecs_user'], str(record['usecs_user']))
            class_info.add_metric([_self.dbhostname, record['classname'], 'usecs_sys'], str(record['usecs_sys']))
            class_info.add_metric([_self.dbhostname, record['classname'], 'readyqueue'], str(record['readyqueue']))
            class_info.add_metric([_self.dbhostname, record['classname'], 'num_ready'], str(record['num_ready']))
            class_info.add_metric([_self.dbhostname, record['classname'], 'idle'], str(record['idle']))
            class_info.add_metric([_self.dbhostname, record['classname'], 'semops'], str(record['semops']))
            class_info.add_metric([_self.dbhostname, record['classname'], 'busy_waits'], str(record['busy_waits']))
            class_info.add_metric([_self.dbhostname, record['classname'], 'spins'], str(record['spins']))
            vpu_classes.append(class_info)
        return vpu_classes

    def get_open_transaction_info(_self):
        record = _self.execute_sql('open_transactions')[0]
        open_transactions = CounterMetricFamily('node_ifx_open_transactions', "Informix transaction info", labels=["ifxserver"])
        open_transactions.add_metric([_self.dbhostname], str(record['open_transactions']))
        return open_transactions

    def get_locks_per_user(_self):
        records = _self.execute_sql('locks_per_user')
        locks = GaugeMetricFamily('node_ifx_locks_user_db', 'Locks per user', labels=["ifxserver", "user"])
        for record in records:
            locks.add_metric([_self.dbhostname, record['username'], ], record['locks'])
        if len(records) == 0:
            # We didn't have any locks - yay!
            # But we still want to report something, so doing it manually
            locks.add_metric([_self.dbhostname, "informix", "sysmaster"], 0)
        return locks

    def get_mutex_info(_self):
        record = _self.execute_sql('mutexes')[0]
        mutex = CounterMetricFamily('node_ifx_mutex', "Informix mutex count", labels=["ifxserver"])
        mutex.add_metric([_self.dbhostname], str(record['mutex_count']))
        return mutex

    def get_thread_info(_self):
        thread_states = GaugeMetricFamily('node_ifx_thread_state', 'Thread states of Informix threads', labels=["ifxserver", "class", "state"])
        states = {0: 'Running',
                  1: 'IO Wait',
                  2: '2-unknown',
                  3: '3-unknown',
                  4: 'Cond Wait',
                  5: 'Terminated',
                  6: '6-unknown',
                  7: 'Sleeping'}
        records = _self.execute_sql('threads')
        for record in records:
            thread_states.add_metric([_self.dbhostname, record['classname'], states[record['threadstate']]], record['count'])
        return thread_states

    def get_buffer_info(_self):
        records = _self.execute_sql('buffers')
        metrics = {}
        counters = ['dskreads','pagreads','bufreads','dskwrites','pagwrites','bufwrites','bufwaits','ovbuff','flushes','fgwrites','lruwrites','chunkwrites','lru_time_total','lru_calls', 'buffer_turnovers']
        for key in counters:
            metrics[key] = CounterMetricFamily('node_ifx_bufferpool_{0}'.format(key), 'Buffer pool value for {0}'.format(key), labels=["ifxserver", "pagesize"])
        gauges = ['size']
        for key in gauges:
            metrics[key] = GaugeMetricFamily('node_ifx_bufferpool_{0}'.format(key), 'Buffer pool value for {0}'.format(key), labels=["ifxserver", "pagesize"])
        for record in records:
            for key in counters+gauges:
                metrics[key].add_metric([_self.dbhostname, str(record['pagesize'])], str(record[key]))
        return metrics

    def get_slow_queries(_self):
        record = _self.execute_sql('slow_queries')[0]
        slow_queries = GaugeMetricFamily('node_ifx_slowquery', 'Thread states of Informix threads', labels=["ifxserver"])
        slow_queries.add_metric([_self.dbhostname], str(record['slow_queries']))
        return slow_queries

    def get_rss_info(_self):
        records = _self.execute_sql('rss_role')
        if len(records) < 1:
            # We're no primary or master server, so we can't know all details.
            # If we're a secondary or a slave, getting this info will hang when we're in trouble or lagging behind
            return []
        records = _self.execute_sql('rss_info')
        logtransrecords = _self.execute_sql('rss_transmit_status')
        metrics = []
        for record in records:
            if record['name'] != _self.ha_alias:
                connection_status = GaugeMetricFamily('node_ifx_rss_connectionstatus', 'RSS connection status', labels=["ifxserver", "node", "nodetype", "connection_status", "server_status", "delayed_apply", "stop_apply"])
                metrics.append(connection_status)
                logtransstatus = -1
                for logtransrecord in logtransrecords:
                    if logtransrecord['server_name'] != _self.ha_alias:
                        if logtransrecord['log_transmission_status'] == "Active":
                            logtransstatus = 1
                        else:
                            logtransstatus = 0
                connection_status.add_metric([_self.dbhostname, record['name'], record['nodetype'], record['connection_status'], record['server_status'], str(record['delayed_apply']), str(record['stop_apply'])], logtransstatus)
            if record['nodetype'] == "RSS":
                replication_lag = GaugeMetricFamily('node_ifx_rss_replication_lag', 'RSS replication lag', labels=["ifxserver", "node", "nodetype"])
                replication_lag.add_metric([_self.dbhostname, record['name'], record['nodetype']], record['lag'])
                metrics.append(replication_lag)
        return metrics
    
    def collect(_self):
        t0 = time.time()
        if _self.connection is None:
            _self.connect()
        else:
            # Single metric functions
            yield _self.get_config_changes()
            yield _self.get_locks_per_user()
            yield _self.get_mutex_info()
            yield _self.get_open_transaction_info()
            yield _self.get_slow_queries()
            yield _self.get_session_info()
            yield _self.get_thread_info()
            # Multi-metric functions
            for res in _self.get_buffer_info().values():
                yield res
            for res in _self.get_dbspaces_info():
                yield res
            for res in _self.get_memory_and_version_info():
                yield res
            for res in _self.get_rss_info():
                yield res
            for res in _self.get_sysprofile_info():
                yield res
            for res in _self.get_uptime_and_mode_info():
                yield res
            for res in _self.get_vpu_class_info():
                yield res
        t1 = time.time()
        execution_time = GaugeMetricFamily('node_ifx_execution_time', 'Time it took to gather statistics', labels=["ifxserver"])
        delta = t1-t0
        if _self.connection is None:
            # If we don't have a valid connection, we'll send the execution time as negative value to signal something is wrong
            execution_time.add_metric([_self.dbhostname], delta*-1)
        else:
            execution_time.add_metric([_self.dbhostname], delta)
        yield execution_time
        _self.print_info("Finished run in {0} seconds".format(delta))

if __name__ == '__main__':
    # Parse the arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, help="Name of the database instance. Eg: ol_informix1410")
    parser.add_argument("--hostname", required=True, help="IP address or hostname where the Informix instance is running")
    parser.add_argument("--port",     required=True, help="TCP port where the Informix instance is running")
    parser.add_argument("--user",     required=True, help="Username to connect to Informix")
    parser.add_argument("--password", required=True, help="Password to connect to Informix")
    parser.add_argument("--httpport", required=True, help="TCP port where the collector will listen on")
    args = parser.parse_args()
    start_http_server(int(args.httpport))
    REGISTRY.register(InformixCollector(database=args.database, hostname=args.hostname, port=args.port, user=args.user, password=args.password))
    while True:
        time.sleep(3)

