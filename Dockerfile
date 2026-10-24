# Frontend build (Debian Buster is EOL — use archive mirrors)
FROM node:10.24.1-buster-slim AS build
RUN sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list \
 && sed -i 's|security.debian.org|archive.debian.org|g' /etc/apt/sources.list \
 && sed -i '/buster-updates/d' /etc/apt/sources.list \
 && echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid \
 && apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
RUN npm install -g gulp@3.9.0
WORKDIR /app
COPY package*.json /app/
RUN npm install
COPY . /app
RUN gulp

# Runtime: base Monitorrent image + TorrentWatch UI + kinozal.guru plugin
FROM werwolfby/monitorrent:1.4.0
COPY monitorrent/plugins/trackers/kinozal.py /var/www/monitorrent/monitorrent/plugins/trackers/kinozal.py
COPY src/content/images/kinozal.guru.png /var/www/monitorrent/webapp/content/images/kinozal.guru.png
COPY --from=build /app/webapp/ /var/www/monitorrent/webapp/
