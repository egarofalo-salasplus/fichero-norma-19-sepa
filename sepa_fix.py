"""
Corrección de ficheros SEPA (ISO 20022) generados por Prinex.

Problema: desde la actualización de Prinex del 29/10/2026 los ficheros
pain.008.001.02 (adeudos, "norma 19") llevan direcciones estructuradas con
elementos que NO existen en esa versión del esquema (p. ej. <BldgNm>), y el
banco rechaza el fichero:

    cvc-complex-type.2.4.a: Se ha encontrado contenido no válido a partir
    del elemento 'BldgNm' ...

Este módulo reescribe cada <PstlAdr> para que cumpla el tipo PostalAddress6
de las versiones antiguas del estándar, sin tocar importes, IBAN, mandatos ni
identificadores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from lxml import etree

# Versiones del estándar cuyo bloque de dirección es PostalAddress6
# (no admiten BldgNm, Flr, Room, PstBx, TwnLctnNm, DstrctNm...).
LEGACY_NAMESPACES = {
    "urn:iso:std:iso:20022:tech:xsd:pain.008.001.01",
    "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02",
    "urn:iso:std:iso:20022:tech:xsd:pain.001.001.02",
    "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03",
}

# Orden y elementos permitidos en PostalAddress6
ALLOWED_ORDER = [
    "AdrTp", "Dept", "SubDept", "StrtNm", "BldgNb",
    "PstCd", "TwnNm", "CtrySubDvsn", "Ctry", "AdrLine",
]
ALLOWED = set(ALLOWED_ORDER)
ADRLINE_MAX = 70
SCHEMAS_DIR = Path(__file__).parent / "schemas"

MODE_LINES = "lineas"    # Ctry + 2 AdrLine (mismo formato que aceptaba el banco)
MODE_MINIMAL = "minimo"  # quitar solo los elementos no permitidos


@dataclass
class Report:
    namespace: str = ""
    applicable: bool = True
    addresses_total: int = 0
    addresses_changed: int = 0
    removed_elements: dict[str, int] = field(default_factory=dict)
    apos_fixed: int = 0
    postcodes_padded: int = 0
    nb_txs: int = 0
    ctrl_sum: Decimal = Decimal("0")
    sum_amounts: Decimal = Decimal("0")
    integrity_ok: bool = False
    structure_ok: bool = False
    xsd_result: str | None = None  # None = sin XSD disponible
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            not self.errors
            and self.integrity_ok
            and self.structure_ok
            and self.xsd_result in (None, "OK")
        )


def _local(tag) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def _txt(el) -> str:
    return re.sub(r"\s+", " ", (el.text or "")).strip() if el is not None else ""


def _fingerprint(root, ns: str) -> list[tuple]:
    """Datos de cada operación que NO deben cambiar nunca."""
    n = {"d": ns}
    out = []
    tx_tags = ("DrctDbtTxInf", "CdtTrfTxInf")
    for el in root.iter():
        if _local(el.tag) in tx_tags:
            vals = []
            for path in ("PmtId/EndToEndId", "InstdAmt", "Amt/InstdAmt",
                         "DrctDbtTx/MndtRltdInf/MndtId",
                         "DbtrAcct/Id/IBAN", "CdtrAcct/Id/IBAN"):
                parts = "/".join(f"d:{p}" for p in path.split("/"))
                found = el.find(parts, n)
                vals.append(found.text if found is not None else None)
            out.append(tuple(vals))
    return out


def _amounts(root) -> list[Decimal]:
    return [Decimal(el.text) for el in root.iter() if _local(el.tag) == "InstdAmt"]


def _fix_apos(root) -> int:
    """'D&aposURGELL' (doble escapado de Prinex) -> "D'URGELL"."""
    count = 0
    pat = re.compile(r"&apos;?")
    for el in root.iter():
        if isinstance(el.tag, str) and el.text and "&apos" in el.text:
            el.text, k = pat.subn("'", el.text)
            count += k
    return count


def _pad_postcode(code: str, country: str) -> tuple[str, bool]:
    if country == "ES" and code.isdigit() and len(code) == 4:
        return "0" + code, True
    return code, False


def _clip(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s[:ADRLINE_MAX].rstrip()


def _rebuild_address(adr, ns: str, mode: str, pad_cp: bool, rep: Report) -> None:
    children = [c for c in adr if isinstance(c.tag, str)]
    names = [_local(c.tag) for c in children]
    bad = [n for n in names if n not in ALLOWED]
    in_order = names == sorted(names, key=lambda x: ALLOWED_ORDER.index(x) if x in ALLOWED else 99)

    vals: dict[str, str] = {}
    adrlines: list[str] = []
    for c, name in zip(children, names):
        if name == "AdrLine":
            adrlines.append(_txt(c))
        else:
            vals[name] = _txt(c)
    country = vals.get("Ctry", "")

    padded = False
    if pad_cp and vals.get("PstCd"):
        vals["PstCd"], padded = _pad_postcode(vals["PstCd"], country)

    if not bad and in_order and not padded:
        return  # dirección ya válida, no se toca

    for b in bad:
        rep.removed_elements[b] = rep.removed_elements.get(b, 0) + 1
    rep.postcodes_padded += int(padded)
    rep.addresses_changed += 1

    def mk(name: str, text: str):
        e = etree.SubElement(adr, f"{{{ns}}}{name}")
        e.text = text
        return e

    for c in children:
        adr.remove(c)

    structured = any(vals.get(k) for k in ("StrtNm", "BldgNb", "PstCd", "TwnNm"))

    if mode == MODE_LINES and structured:
        # Formato idéntico al fichero que el banco sí acepta:
        # <Ctry>ES</Ctry><AdrLine>calle, N num extra</AdrLine><AdrLine>CP ciudad prov</AdrLine>
        extras = " ".join(vals[n] for n in names if n not in ALLOWED and vals.get(n))
        # Etiquetas vacías que deja Prinex ("Escalera  " sin valor)
        extras = re.sub(r"\b(Escalera|Esc\.|Piso|Puerta|Pta\.)\s*$", "", extras, flags=re.I).strip()
        line1 = vals.get("StrtNm", "")
        if vals.get("BldgNb"):
            line1 += f", N {vals['BldgNb']}"
        if extras:
            line1 += f" {extras}"
        town, prov = vals.get("TwnNm", ""), vals.get("CtrySubDvsn", "")
        line2 = " ".join(p for p in (vals.get("PstCd", ""), town,
                                     prov if prov.upper() != town.upper() else "") if p)
        if vals.get("AdrTp"):
            mk("AdrTp", vals["AdrTp"])
        if country:
            mk("Ctry", country)
        lines = [l for l in (_clip(line1), _clip(line2)) if l] + [l for l in adrlines if l]
        if len(lines) > 2:
            rep.warnings.append(
                f"Dirección con más de 2 líneas; se conservan las 2 primeras: {lines}")
            lines = lines[:2]
        for l in lines:
            mk("AdrLine", l)
    else:
        # Modo mínimo: solo elementos permitidos, en el orden correcto
        for name in ALLOWED_ORDER:
            if name == "AdrLine":
                for l in adrlines[:7]:
                    mk("AdrLine", _clip(l))
            elif vals.get(name):
                mk(name, vals[name])


def _check_structure(root) -> list[str]:
    problems = []
    for adr in root.iter():
        if _local(adr.tag) != "PstlAdr":
            continue
        names = [_local(c.tag) for c in adr if isinstance(c.tag, str)]
        bad = [n for n in names if n not in ALLOWED]
        order = [ALLOWED_ORDER.index(n) for n in names if n in ALLOWED]
        if bad or order != sorted(order) or names.count("AdrLine") > 7:
            problems.append(f"Dirección no válida (línea {adr.sourceline}): {names}")
    return problems


def _xsd_validate(xml_bytes: bytes, ns: str) -> str | None:
    version = ns.rsplit(":", 1)[-1]  # p. ej. pain.008.001.02
    xsd_path = SCHEMAS_DIR / f"{version}.xsd"
    if not xsd_path.exists():
        return None
    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    doc = etree.fromstring(xml_bytes)
    if schema.validate(doc):
        return "OK"
    return "; ".join(f"línea {e.line}: {e.message}" for e in list(schema.error_log)[:5])


def fix_sepa(xml_bytes: bytes, mode: str = MODE_LINES,
             fix_apos: bool = True, pad_cp: bool = True) -> tuple[bytes | None, Report]:
    rep = Report()
    parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False, no_network=True)
    try:
        root = etree.fromstring(xml_bytes, parser)
    except etree.XMLSyntaxError as e:
        rep.errors.append(f"El fichero no es un XML válido: {e}")
        return None, rep

    ns = etree.QName(root.tag).namespace or ""
    rep.namespace = ns
    if ns not in LEGACY_NAMESPACES:
        rep.applicable = False
        rep.warnings.append(
            f"El fichero usa '{ns.rsplit(':', 1)[-1]}'. Esta herramienta solo corrige "
            "pain.008.001.02 / pain.001.001.03; no se ha modificado.")

    before = _fingerprint(root, ns)
    amounts_before = _amounts(root)

    if rep.applicable:
        if fix_apos:
            rep.apos_fixed = _fix_apos(root)
        for adr in [e for e in root.iter() if _local(e.tag) == "PstlAdr"]:
            rep.addresses_total += 1
            _rebuild_address(adr, ns, mode, pad_cp, rep)

    # --- Controles de integridad -------------------------------------------
    after = _fingerprint(root, ns)
    amounts = _amounts(root)
    rep.sum_amounts = sum(amounts, Decimal("0"))
    hdr_n = root.find(".//{*}GrpHdr/{*}NbOfTxs")
    hdr_s = root.find(".//{*}GrpHdr/{*}CtrlSum")
    rep.nb_txs = int(hdr_n.text) if hdr_n is not None else len(amounts)
    rep.ctrl_sum = Decimal(hdr_s.text) if hdr_s is not None else rep.sum_amounts

    if before != after or amounts_before != amounts:
        rep.errors.append("Los datos de las operaciones han cambiado. NO usar el fichero.")
    if rep.nb_txs != len(amounts):
        rep.errors.append(f"NbOfTxs ({rep.nb_txs}) no coincide con las operaciones ({len(amounts)}).")
    if rep.ctrl_sum != rep.sum_amounts:
        rep.errors.append(f"CtrlSum ({rep.ctrl_sum}) no coincide con la suma ({rep.sum_amounts}).")
    rep.integrity_ok = not rep.errors

    problems = _check_structure(root)
    rep.structure_ok = not problems
    rep.errors.extend(problems)

    out = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    rep.xsd_result = _xsd_validate(out, ns)
    if rep.xsd_result not in (None, "OK"):
        rep.errors.append(f"Validación XSD: {rep.xsd_result}")

    return out, rep
