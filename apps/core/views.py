from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render


def salud(request):
    """Verificación de salud: responde 200 si la aplicación y la base de datos están vivas."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"estado": "ok", "base_de_datos": "ok"})
    except Exception:  # noqa: BLE001
        return JsonResponse({"estado": "error", "base_de_datos": "sin conexión"}, status=503)


@login_required
def inicio(request):
    return render(request, "inicio.html")
