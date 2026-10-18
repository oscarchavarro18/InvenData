def test_salud_responde_ok(client, db):
    respuesta = client.get("/salud/")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "ok", "base_de_datos": "ok"}


def test_inicio_exige_sesion(client, db):
    respuesta = client.get("/")
    assert respuesta.status_code == 302
    assert respuesta.url.startswith("/login/")
