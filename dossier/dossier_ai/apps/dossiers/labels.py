"""Etiquetas legibles (español) para identificadores técnicos que se muestran en la interfaz.

Solo afecta a la presentación: los identificadores internos (reglas, campos, tipos) no cambian en la base de datos,
la API ni el motor de reglas."""
from __future__ import annotations

import re

APPROVED, NOT_APPROVED = "Aprobado", "No aprobado"

DOC_TYPES = {
    "escritura": "Escritura", "predial": "Boleta predial", "alineamiento": "Alineamiento y número oficial",
    "uso_suelo": "Uso de suelo", "no_reconocido": "No reconocido",
}

FIELDS = {
    "titular": "Titular", "direccion": "Dirección", "identificacion_inmueble": "Identificación del inmueble",
    "superficie_terreno": "Superficie del terreno", "datos_relevantes": "Datos relevantes",
    "propietario": "Propietario", "cuenta_predial": "Cuenta predial", "superficie_registrada": "Superficie registrada",
    "direccion_oficial": "Dirección oficial", "numero_oficial": "Número oficial",
    "identificacion_predio": "Identificación del predio", "alineamiento": "Alineamiento",
    "fecha_emision": "Fecha de emisión", "vigencia": "Vigencia", "autoridad_emisora": "Autoridad emisora",
    "uso_autorizado": "Uso autorizado", "compatibilidad_uso_comercial": "Compatibilidad con uso comercial",
    "restricciones": "Restricciones", "superficie_aplicable": "Superficie aplicable",
    "superficie": "Superficie", "identificacion_predio_cruzada": "Identificación del predio",
}

RULES = {
    "escritura.titular.presente": "Escritura: titular identificado",
    "escritura.superficie.presente": "Escritura: superficie del terreno",
    "predial.cuenta.presente": "Predial: cuenta o clave predial",
    "predial.propietario.presente": "Predial: propietario",
    "alineamiento.numero.presente": "Alineamiento: número oficial",
    "alineamiento.vigencia": "Alineamiento: documento vigente",
    "uso_suelo.uso.presente": "Uso de suelo: uso autorizado",
    "uso_suelo.vigencia": "Uso de suelo: documento vigente",
    "uso_suelo.compatibilidad": "Uso de suelo: compatible con uso comercial",
    "uso_suelo.restricciones.informadas": "Uso de suelo: restricciones declaradas",
    "ESC-01": "Escritura: titular identificado",
    "ESC-02": "Escritura: superficie del terreno mayor a 0 m²",
    "PRE-01": "Predial: cuenta o clave catastral",
    "ALI-01": "Alineamiento: número oficial",
    "ALI-02": "Alineamiento: documento vigente",
    "USO-01": "Uso de suelo: compatible con uso comercial",
    "USO-02": "Uso de suelo: documento vigente",
    "USO-03": "Uso de suelo: restricciones o condicionantes",
}

OUTCOMES = {"cumple": "Cumple", "no_cumple": "No cumple", "indeterminada": "Por revisar"}
SEVERITIES = {"critico": "Crítico", "relevante": "Relevante", "informativo": "Informativo"}
CATEGORIES = {"requisito": "Requisito", "vigencia": "Vigencia", "restriccion": "Restricción", "completitud": "Completitud"}
VERIFICATION = {"verificada": "Verificada", "no_verificada": "No verificada", "pendiente": "Pendiente",
                "corregida_manualmente": "Corregida manualmente"}
KINDS = {"formato": "Solo difiere el formato", "real": "Diferencia real", "tolerancia_pendiente": "Diferencia fuera de tolerancia"}
AGENTS = {"ingesta": "Ingesta de documentos", "clasificador": "Clasificación", "detector_faltantes": "Documentos faltantes",
          "extractores": "Extracción de datos", "verificador_evidencia": "Verificación de evidencia",
          "validadores_reglas": "Validación de reglas", "validacion_cruzada": "Validación cruzada", "dictaminador": "Dictamen final"}

LOOKUP = {**DOC_TYPES, **FIELDS, **RULES, **OUTCOMES, **SEVERITIES, **CATEGORIES, **VERIFICATION, **KINDS}

# Para texto libre solo se reemplazan identificadores inequívocos (con "_" o "." o código de regla), nunca palabras comunes.
_TOKENS = sorted((k for k in {**RULES, **DOC_TYPES, **FIELDS} if "_" in k or "." in k or "-" in k), key=len, reverse=True)
_TOKEN_RE = re.compile(r"(?<![\w.])(" + "|".join(re.escape(t) for t in _TOKENS) + r")(?![\w])")
_MAP = {**RULES, **DOC_TYPES, **FIELDS}


def label(value) -> str:
    s = str(value)
    return LOOKUP.get(s, s)


_MISSING_RE = re.compile(r"(Documentos faltantes:\s*)([^.]*)")


def humanize(text) -> str:
    out = _TOKEN_RE.sub(lambda m: _MAP[m.group(1)], str(text))
    # La lista de faltantes usa los valores internos de tipo documental ("alineamiento", "predial"…): se traducen aquí.
    return _MISSING_RE.sub(lambda m: m.group(1) + ", ".join(DOC_TYPES.get(p.strip(), p.strip()) for p in m.group(2).split(",")), out)


def is_approved(recommendation: str) -> bool:
    return recommendation == "cumple"


def verdict_label(recommendation: str) -> str:
    if not recommendation:
        return ""
    return APPROVED if is_approved(recommendation) else NOT_APPROVED
