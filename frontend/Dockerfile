# Static web page only: no Python, no model code. It reaches the backend through API_URL.
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html config.json /usr/share/nginx/html/
COPY vendor /usr/share/nginx/html/vendor
COPY 40-config.sh /docker-entrypoint.d/40-config.sh
