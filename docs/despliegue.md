# Despliegue de InvenData en un VPS

Guía para poner InvenData en producción en un servidor propio, con HTTPS y copias de
seguridad diarias. Toma entre 30 y 60 minutos la primera vez.

## Cómo queda montado

```
Internet ──► nginx (80 y 443, HTTPS) ──► web (Django + Gunicorn) ──► db (PostgreSQL 16)
                │                              │
             certbot                     volumen «media»
      (renueva el certificado)        (fotos y evidencias)
```

- Solo nginx queda expuesto a internet. La aplicación y la base viven en la red interna de Docker.
- Las fotos y evidencias nunca se publican como archivos: se entregan a través de la aplicación,
  que revisa el perfil de quien las pide.
- El certificado HTTPS es gratuito (Let's Encrypt) y se renueva solo.
- Los datos viven en volúmenes de Docker (`pgdata`, `media`, `letsencrypt`): sobreviven a
  reinicios y actualizaciones.

## 1. Lo que se necesita

- **Un VPS** con Ubuntu 24.04 (o 22.04), de 2 GB de RAM y 20 GB de disco como mínimo.
- **Un dominio** o subdominio, por ejemplo `inventario.pidconsulting.com`, con un registro **A**
  que apunte a la IP del VPS. Compruébelo con `ping inventario.pidconsulting.com`.
- **Acceso SSH** al VPS con un usuario que pueda usar `sudo`.

## 2. Preparar el servidor (una sola vez)

```bash
# Actualizar e instalar Docker
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # salga y vuelva a entrar por SSH para que aplique

# Cortafuegos: solo SSH, HTTP y HTTPS
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# Hora de Colombia (las fechas de los registros salen en hora local de todos modos)
sudo timedatectl set-timezone America/Bogota
```

## 3. Bajar el proyecto y configurarlo

```bash
sudo mkdir -p /opt/invendata && sudo chown $USER /opt/invendata
git clone https://github.com/oscarchavarro18/InvenData.git /opt/invendata
cd /opt/invendata
git checkout main          # producción usa la rama main
cp .env.prod.example .env
nano .env
```

En el `.env`, complete:

| Variable | Qué poner |
|---|---|
| `DJANGO_SECRET_KEY` | La salida de `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_ALLOWED_HOSTS` | El dominio, por ejemplo `inventario.pidconsulting.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | El dominio con `https://` delante |
| `POSTGRES_PASSWORD` | La salida de `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DOMINIO` | El dominio, sin `https://` |
| `CORREO_CERTIFICADOS` | Un correo que reciba los avisos de Let's Encrypt |

El `.env` tiene las claves del sistema: protéjalo con `chmod 600 .env` y nunca lo comparta.

## 4. Primer arranque y certificado HTTPS

```bash
make prod-up              # construye la imagen y levanta todo; aplica las migraciones solo
make prod-ps              # db, web, nginx y certbot deben decir «Up»
make prod-certificado     # pide el certificado y reinicia nginx con HTTPS
```

Abra `https://SU-DOMINIO`: debe aparecer la pantalla de ingreso con el candado.

Si `make prod-certificado` falla, casi siempre es el DNS: el dominio todavía no apunta a la IP
del VPS o el puerto 80 está cerrado. Revise con `make prod-logs`.

## 5. Crear la gerencia y cargar los datos iniciales

```bash
make prod-superusuario    # crea el usuario del Gerente (pide usuario, nombre y contraseña)
```

Luego, desde el navegador y como Gerente:

1. **Administración → Ubicaciones:** las zonas de la bodega y los puntos de venta.
2. **Administración → Tipos de embalaje:** canastillas y cajas con su tara, y «Sin embalaje» con tara 0.
3. **Administración → Categorías, Productos, Proveedores y Clientes.**
4. **Administración → Parámetros:** confirmar la tolerancia de transformación.
5. **Administración → Usuarios:** un usuario por persona, con su perfil. Cada Administrador de
   PDV, con su punto de venta.
6. **Inventario inicial:** el levantamiento de cada ubicación. Cuando el Gerente lo aprueba, el
   sistema empieza a operar con esa existencia (RF-62).

No cargue datos de demostración en producción.

## 6. Copias de seguridad diarias

```bash
sudo mkdir -p /var/backups/invendata && sudo chown $USER /var/backups/invendata
make prod-respaldo        # primera copia de prueba; debe decir «respaldo correcto»
crontab -e
```

Agregue esta línea para que corra todos los días a las 2:30 a. m.:

```
30 2 * * * cd /opt/invendata && sh docker/respaldo.sh >> /var/log/invendata-respaldo.log 2>&1
```

Cada copia trae la base de datos (`base-*.dump`) y las fotos (`fotos-*.tar.gz`). El script
comprueba que se pueden leer y borra las de más de 14 días.

**Saque copias fuera del servidor** al menos una vez por semana (por ejemplo, con `scp` a otro
equipo, o a un almacenamiento en la nube): si el VPS se pierde, las copias guardadas dentro de
él se pierden con él.

### Restaurar una copia

```bash
sh docker/restaurar.sh /var/backups/invendata/base-AAAAMMDD-HHMM.dump /var/backups/invendata/fotos-AAAAMMDD-HHMM.tar.gz
```

Pide escribir `RESTAURAR` para confirmar, porque reemplaza los datos actuales. Ensaye una
restauración en un servidor de prueba antes de necesitarla de verdad.

## 7. Actualizar a una versión nueva

```bash
cd /opt/invendata
make prod-respaldo        # siempre una copia antes de actualizar
git pull
make prod-up              # reconstruye y reinicia; las migraciones se aplican solas
make prod-ps
```

Si algo sale mal: `git checkout <commit-anterior>`, `make prod-up`, y si hizo falta, restaure la
copia que sacó antes de actualizar.

## 8. Después de comprobar que HTTPS funciona

Cuando lleve unos días sin problemas, suba en el `.env` `DJANGO_HSTS_SECONDS=31536000` (un año)
y ejecute `make prod-up`. Así los navegadores ya no intentan entrar por HTTP.

## 9. Comprobaciones rápidas

| Qué revisar | Cómo |
|---|---|
| Que todo esté arriba | `make prod-ps` |
| Errores de la aplicación | `make prod-logs` |
| Salud del sistema | `curl https://SU-DOMINIO/salud/` debe responder `{"estado": "ok", ...}` |
| Vencimiento del certificado | `docker compose -f docker-compose.prod.yml run --rm --entrypoint certbot certbot certificates` |
| Última copia | `ls -lt /var/backups/invendata | head` y `tail /var/log/invendata-respaldo.log` |
| Espacio en disco | `df -h` |
