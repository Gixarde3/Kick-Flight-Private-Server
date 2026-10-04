FROM alpine:3.23

RUN apk add --no-cache ca-certificates curl gzip libmaxminddb

COPY deploy/geoip/update-dbip-country.sh /usr/local/bin/update-dbip-country
RUN chmod 0755 /usr/local/bin/update-dbip-country

ENTRYPOINT ["/usr/local/bin/update-dbip-country"]
