# traefik reverse proxy

Edit `/etc/docker/daemon.json`

```json
{
    "userland-proxy": false
}
```

`docker network create --subnet 172.18.0.0/16 --ipv6 --subnet fd90:1234:5678:beef::/64 traefik`
