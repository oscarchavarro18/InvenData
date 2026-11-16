# Lo común a todo lo que va hacia la aplicación.
client_max_body_size 8m;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_read_timeout 90s;
proxy_send_timeout 90s;
