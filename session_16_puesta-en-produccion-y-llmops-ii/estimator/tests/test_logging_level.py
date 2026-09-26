"""El nivel de log filtra de verdad.

Existe porque hasta la Sesión 15 no lo hacía. `LOG_LEVEL` estaba declarada,
tipada y llegaba al contenedor, pero `structlog.configure` no la miraba:
`add_log_level` sólo ANOTA el nivel en el evento, no descarta nada. El servicio
escribía sus 181 eventos pasara lo que pasara, y en producción —salida JSON— no
había forma de bajar el volumen.

Un mando desconectado no se nota mirando la pantalla: se nota en la factura del
agregador de logs, tres meses después. De ahí este test.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest
import structlog

from app import main


def _configurar(monkeypatch, nivel: str) -> None:
    ajustes = type("S", (), {"APP_ENV": "development", "LOG_LEVEL": nivel})()
    monkeypatch.setattr(main, "get_settings", lambda: ajustes)
    main.configure_logging()


def _emitir() -> str:
    """Un evento por nivel, capturando lo que llega a stdout."""
    # Un logger NUEVO por llamada: `cache_logger_on_first_use=True` congela el
    # wrapper en el primer uso, así que reciclar uno se saltaría la reconfiguración.
    log = structlog.get_logger("prueba").bind()
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        log.debug("evento_debug")
        log.info("evento_info")
        log.warning("evento_warning")
        log.error("evento_error")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _restaurar():
    yield
    structlog.reset_defaults()


def test_con_debug_sale_todo(monkeypatch):
    _configurar(monkeypatch, "DEBUG")

    salida = _emitir()

    for evento in ("evento_debug", "evento_info", "evento_warning", "evento_error"):
        assert evento in salida


def test_con_warning_se_callan_debug_e_info(monkeypatch):
    # Éste es el que fallaba antes de cablearlo: salían los cuatro.
    _configurar(monkeypatch, "WARNING")

    salida = _emitir()

    assert "evento_debug" not in salida
    assert "evento_info" not in salida
    assert "evento_warning" in salida
    assert "evento_error" in salida


def test_con_error_solo_sale_error(monkeypatch):
    _configurar(monkeypatch, "ERROR")

    salida = _emitir()

    assert salida.count("evento_") == 1
    assert "evento_error" in salida


def test_el_nivel_sigue_anotado_en_el_evento(monkeypatch):
    # Filtrar no puede costar la etiqueta: los logs de producción son JSON y el
    # agregador filtra por ese campo, no por el texto.
    _configurar(monkeypatch, "INFO")

    assert "info" in _emitir()


def test_un_nivel_inventado_no_llega_hasta_aqui():
    """La defensa está en el Literal de Settings, y es deliberado: un nivel mal
    escrito tiene que reventar al arrancar, no al primer log que no salga."""
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(OPENAI_API_KEY="x", LOG_LEVEL="TRACE")
