FROM docker:27-cli

RUN apk add --no-cache bash python3 curl git

WORKDIR /app

COPY infra/services/manager/entrypoint.sh /app/entrypoint.sh
COPY infra/services/manager/manage_services.py /app/manage_services.py

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
