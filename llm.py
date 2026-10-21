"""Interfaz LLM intercambiable. Por defecto Claude (SDK `anthropic`).

Si no hay credenciales, `disponible()` devuelve False y los módulos usan su
respaldo por reglas; nunca se inventa una respuesta.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Protocol

import config

log = logging.getLogger(__name__)


class ProveedorLLM(Protocol):
    def completar(self, sistema: str, mensaje: str, max_tokens: int = 2000, esfuerzo: str = "low") -> str: ...


class ClaudeLLM:
    def __init__(self, modelo: str = config.LLM_MODEL):
        import anthropic

        self._anthropic = anthropic
        self.cliente = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None)
        self.modelo = modelo

    def completar(self, sistema: str, mensaje: str, max_tokens: int = 2000, esfuerzo: str = "low") -> str:
        resp = self.cliente.messages.create(
            model=self.modelo,
            max_tokens=max_tokens,
            system=sistema,
            output_config={"effort": esfuerzo},
            messages=[{"role": "user", "content": mensaje}],
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("El modelo rechazó la solicitud")
        return "".join(b.text for b in resp.content if b.type == "text").strip()


@lru_cache(maxsize=1)
def obtener() -> ProveedorLLM | None:
    """Devuelve el proveedor configurado o None si no hay credenciales."""
    if not config.ANTHROPIC_API_KEY:
        log.info("Sin ANTHROPIC_API_KEY: se usa el modo por reglas (sin LLM).")
        return None
    try:
        return ClaudeLLM()
    except Exception as e:  # SDK ausente o mal configurado
        log.warning("No se pudo iniciar el LLM: %s", e)
        return None


def disponible() -> bool:
    return obtener() is not None


def completar_json(sistema: str, mensaje: str, max_tokens: int = 1000) -> dict | None:
    """Pide al LLM un objeto JSON y lo parsea; None si falla."""
    proveedor = obtener()
    if proveedor is None:
        return None
    try:
        texto = proveedor.completar(sistema + "\nResponde SOLO con un objeto JSON válido.", mensaje, max_tokens)
        m = re.search(r"\{.*\}", texto, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:
        log.warning("Fallo LLM JSON: %s", e)
        return None
