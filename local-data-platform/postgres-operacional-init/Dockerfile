FROM postgres:16

COPY bootstrap.sh /bootstrap.sh
COPY init.sql /init.sql

RUN chmod +x /bootstrap.sh

ENTRYPOINT ["/bootstrap.sh"]
