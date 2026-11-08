"""Filtros de la consulta de auditoría (RF-10)."""

from django import forms

from apps.accounts.models import Usuario
from apps.auditoria.consultas import entidades
from apps.auditoria.models import AccionAuditoria
from apps.reportes.forms import FiltrosForm, PeriodoMixin


class AuditoriaFiltrosForm(PeriodoMixin, FiltrosForm):
    usuario = forms.ModelChoiceField(
        label="Usuario", queryset=Usuario.objects.none(), required=False, empty_label="Todos"
    )
    entidad = forms.ChoiceField(label="Módulo", required=False, initial="")
    accion = forms.ChoiceField(
        label="Acción",
        choices=[("", "Todas"), *AccionAuditoria.choices],
        required=False,
        initial="",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["usuario"].queryset = Usuario.objects.order_by("nombre_completo")
        self.fields["entidad"].choices = [("", "Todos"), *entidades()]
