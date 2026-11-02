import io
import zipfile
from pathlib import Path

import streamlit as st

from sepa_fix import MODE_LINES, MODE_MINIMAL, fix_sepa

st.set_page_config(page_title="Corrector SEPA Prinex", page_icon="🏦", layout="centered")

st.title("Corrector de remesas SEPA (Prinex)")
st.caption(
    "Corrige los ficheros XML de adeudos (norma 19 / pain.008.001.02) que Prinex genera "
    "desde la actualización del 29/10/2026 y que el banco rechaza con el error "
    "*«contenido no válido a partir del elemento BldgNm»*."
)

with st.expander("¿Qué hace exactamente?"):
    st.markdown(
        """
- Reescribe **solo las direcciones postales** (`PstlAdr`) al formato que el banco ya aceptaba:
  país + 2 líneas de dirección.
- **No toca** importes, IBAN, BIC, mandatos, fechas de cobro ni conceptos.
- Antes de dejarte descargar, comprueba que el número de operaciones, la suma de control y
  los datos de cada recibo son **idénticos** al original.
- Los ficheros **no se guardan**: se procesan en memoria y se descartan.
"""
    )

with st.expander("Opciones avanzadas"):
    mode = st.radio(
        "Formato de dirección",
        [MODE_LINES, MODE_MINIMAL],
        format_func=lambda m: {
            MODE_LINES: "Líneas de dirección, igual que los ficheros aceptados (recomendado)",
            MODE_MINIMAL: "Mantener campos separados y quitar solo los no permitidos",
        }[m],
    )
    fix_apos = st.checkbox("Corregir apóstrofos mal codificados (D&aposURGELL → D'URGELL)", True)
    pad_cp = st.checkbox("Completar códigos postales de 4 cifras (8010 → 08010)", True)

files = st.file_uploader(
    "Arrastra aquí los ficheros XML que ha generado Prinex",
    type=["xml"],
    accept_multiple_files=True,
)

if not files:
    st.info("Puedes subir varios ficheros a la vez.")
    st.stop()

results = []
for f in files:
    out, rep = fix_sepa(f.getvalue(), mode=mode, fix_apos=fix_apos, pad_cp=pad_cp)
    name = f"{Path(f.name).stem}_CORREGIDO.xml"
    results.append((f.name, name, out, rep))

    with st.container(border=True):
        if not rep.applicable:
            st.warning(f"**{f.name}** — no aplica")
        elif rep.ok:
            st.success(f"**{f.name}** — listo para enviar al banco")
        else:
            st.error(f"**{f.name}** — NO enviar este fichero")

        c1, c2, c3 = st.columns(3)
        c1.metric("Recibos", rep.nb_txs)
        c2.metric("Importe total", f"{rep.ctrl_sum:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
        c3.metric("Direcciones corregidas", f"{rep.addresses_changed} / {rep.addresses_total}")

        details = []
        if rep.removed_elements:
            details.append("Campos no admitidos eliminados: " + ", ".join(
                f"`{k}` ×{v}" for k, v in rep.removed_elements.items()))
        if rep.apos_fixed:
            details.append(f"Apóstrofos corregidos: {rep.apos_fixed}")
        if rep.postcodes_padded:
            details.append(f"Códigos postales completados: {rep.postcodes_padded}")
        details.append("Importes, IBAN y mandatos: " + ("✅ sin cambios" if rep.integrity_ok else "❌ revisar"))
        details.append("Validación XSD oficial: " + {
            None: "no configurada (se ha hecho la comprobación de estructura de direcciones)",
            "OK": "✅ correcta",
        }.get(rep.xsd_result, "❌ con errores"))
        st.markdown("\n".join(f"- {d}" for d in details))

        for w in rep.warnings:
            st.warning(w)
        for e in rep.errors:
            st.error(e)

        if rep.ok and rep.applicable:
            st.download_button(
                f"⬇️ Descargar {name}", out, file_name=name,
                mime="application/xml", key=f"dl_{f.name}",
            )

good = [(n, o) for _, n, o, r in results if r.ok and r.applicable]
if len(good) > 1:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, o in good:
            z.writestr(n, o)
    st.download_button("⬇️ Descargar todos (ZIP)", buf.getvalue(),
                       file_name="remesas_corregidas.zip", mime="application/zip",
                       type="primary")
