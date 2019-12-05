# prometheus-informix-collector

This python script runs standalone and exposes a number of informix parameters for monitoring. I'm running this on an ubuntu 18.04, but I would expect it to be OS independent.

## Dependencies

* The IBM Informix client SDK (I have it installed under _/opt/IBM/Informix_Client-SDK_)
* `pip install IfxPy`
* `pip install prometheus_client`

If your client SDK is installed somewhere else, change the LD_LIBRARY_PATH environment variable to your location

## How to run

`python /path/to/informix_prometheus_collector.py --database ol_informix1210 --hostname 192.168.56.101 --port 9088 --user informix --password informix --httpport 8000`

* database: the name of your database instance (typically `echo $INFORMIXSERVER`)
* hostname: the IP address or hostname of your database server
* port: the TCP port where we can connect to
* user: a username who has connect and select on the sysmaster database and its tables
* password: the password of said user
* httpport: the port where the prometheus metrics are reachable for your prometheus to request them

### Running as a service

If you really want to, you can run this as a service. Put this in `/lib/system/systemd/prometheus-informix-collector.service`:

```
[Unit]
Description=Prometheus exporter for a (remote) informix server
Documentation=

[Service]
Type=simple
Restart=always
User=prometheus
ExecStart=/opt/informix_collector/informix_prometheus_collector.py --database ol_informix1210 --hostname 192.168.56.101 --port 9088 --user informix --password informix --httpport 8000
TimeoutStopSec=20s
OOMScoreAdjust=1000
RestartSec=10s
Restart=always

[Install]
WantedBy=multi-user.target
```

## Disclaimer

Use this at your own risk. I'm no real programmer ;-)
