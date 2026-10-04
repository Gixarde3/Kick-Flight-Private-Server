FROM alpine:3.23

# Alpine publishes nginx and its GeoIP2 module from the same build, keeping the
# dynamic module ABI aligned instead of mixing it with nginx.org's image binary.
RUN apk add --no-cache nginx nginx-mod-http-geoip2 libmaxminddb \
    && mkdir -p /usr/share/nginx/html /var/cache/nginx /var/log/nginx

COPY deploy/nginx/geoip-enabled.conf /etc/nginx/geoip-enabled.conf
COPY deploy/nginx/geoip-disabled.conf /etc/nginx/geoip-disabled.conf
COPY deploy/nginx/entrypoint.sh /usr/local/bin/kickflight-nginx-entrypoint
RUN chmod 0755 /usr/local/bin/kickflight-nginx-entrypoint

ENTRYPOINT ["/usr/local/bin/kickflight-nginx-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
