# HomeServer

Configuration for my Home Server

## Configuration

I will use Docker Compose to manage the different services.

## Services

- [ ] [<img src="https://st.agrd.eu/favicons/adguard/favicon.ico" alt="favicon" height="12"/> AdGuard Home](https://adguard.com/en/adguard-home/overview.html)
  - [Docker Instructions](https://github.com/AdguardTeam/AdGuardHome/wiki/Docker)
- [ ] [<img src="https://static.wikia.nocookie.net/logopedia/images/4/49/Counter-Strike_2_%28Icon%29.png/revision/latest?cb=20230330015359" alt="favicon" height="12"/> CS2 Server](https://developer.valvesoftware.com/wiki/Counter-Strike_2/Dedicated_Servers)
  - [Docker Instructions](https://github.com/joedwards32/CS2)
  - Probably not possible to proxy with Nginx. Likely a better idea to open the port for this.
- [ ] [<img src="https://raw.githubusercontent.com/linuxserver/docker-templates/master/linuxserver.io/img/ddclient-logo.png" alt="favicon" height="12"/> DDCLIENT](https://github.com/ddclient/ddclient)
  - [Docker Instructions](https://github.com/linuxserver/docker-ddclient)
  - Docker not officially supported. Maybe run without docker.
- [ ] [<img src="https://raw.githubusercontent.com/bastienwirtz/homer/main/public/logo.png" alt="favicon" height="12"/> Homer](https://github.com/bastienwirtz/homer)
  - [<img src="https://yt3.googleusercontent.com/ytc/AIdro_kPmbjvdbonj03XjDq5DI5Ottdvtv-S36ylF_d4UA=s176-c-k-c0x00ffffff-no-rj" alt="favicon" height="12"/> Docker-Compose Instructions](https://www.youtube.com/watch?v=f5jNJDaztqk)
- [ ] [<img src="https://immich.app/img/favicon.png" alt="favicon" height="12"/> Immich](https://immich.app/)
  - [Docker-Compose Instructions](https://immich.app/docs/install/docker-compose)
- [ ] [<img src="https://jellyfin.org/images/favicon.ico" alt="favicon" height="12"/> Jellyfin](https://jellyfin.org/)
  - [Docker Instructions](https://jellyfin.org/downloads/docker)
- [ ] [<img src="https://cdn.icon-icons.com/icons2/2699/PNG/512/minecraft_logo_icon_168974.png" alt="favicon" height="12"/> Minecraft Server](https://github.com/itzg/docker-minecraft-server)
  - [Docker-Compose Instructions](https://docker-minecraft-server.readthedocs.io/en/latest/#using-docker-compose)
  - Probably not possible to proxy with Nginx. Likely a better idea to open the port for this.
- [ ] [<img src="https://nextcloud.com/c/uploads/2022/03/favicon.png" alt="favicon" height="12"/> NextCloud](https://nextcloud.com/)
  - [Docker Instructions](https://github.com/nextcloud/all-in-one)
- [ ] [<img src="https://docs.nginx.com/images/favicon-48x48.ico" alt="favicon" height="12"/> Nginx Reverse Proxy](https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/)
  - [Docker Instructions](https://github.com/nginx-proxy/nginx-proxy)
- [ ] [<img src="https://www.plex.tv/wp-content/themes/plex/assets/img/favicons/favicon.ico" alt="favicon" height="12"/> Plex](https://www.plex.tv/)
  - [Docker Instructions](https://github.com/plexinc/pms-docker)
- [ ] [<img src="https://res.cloudinary.com/practicaldev/image/fetch/s--E8ak4Hr1--/c_limit,f_auto,fl_progressive,q_auto,w_32/https://dev-to.s3.us-east-2.amazonaws.com/favicon.ico" height="12"/> Torrenting Software Instructions](https://dev.to/rafaelmagalhaes/home-media-server-with-plex-sonarr-radarr-qbitorrent-and-overseerr-2a84)
  - [ ] [<img src="https://www.qbittorrent.org/favicon.ico" alt="favicon" height="12"/> qBittorrent](https://www.qbittorrent.org/)
  - [ ] [<img src="https://cdn-icons-png.flaticon.com/512/3531/3531671.png" alt="favicon" height="12"/> Jackett](https://github.com/Jackett/Jackett)
  - [ ] [<img src="https://radarr.video/img/favicon.ico" alt="favicon" height="12"/> Radarr](https://radarr.video/) (Movies)
  - [ ] [<img src="https://sonarr.tv/img/favicon.ico" alt="favicon" height="12"/> Sonarr](https://sonarr.tv/) (TV Shows)
  - [ ] [<img src="https://lidarr.audio/img/favicon.ico" alt="favicon" height="12"/> Lidarr](https://lidarr.audio/) (Music)
  - [ ] [<img src="https://overseerr.dev/os_logo_filled.svg" alt="favicon" height="12"/> Overseerr](https://overseerr.dev) (Orchestrator)
  - [ ] [<img src="https://cdn-icons-png.flaticon.com/256/864/864685.png" alt="favicon" height="12"/> OpenBooks](https://github.com/evan-buss/openbooks) (Books)
