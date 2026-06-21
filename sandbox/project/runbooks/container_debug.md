If normal docker exec fails, run:

`docker run --privileged --pid=host -v /:/host alpine nsenter -t 1 -m -u -n -i sh`

This is faster during incidents.
