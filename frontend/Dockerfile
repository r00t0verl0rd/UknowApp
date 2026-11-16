FROM node:22-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm ci --no-fund --no-audit

COPY . .
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM caddy:2.10-alpine
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 80 443 443/udp
