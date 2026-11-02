# Corrector de remesas SEPA (Prinex)

Herramienta web (Streamlit) para que Contabilidad corrija los ficheros XML de
adeudos SEPA que genera Prinex y que el banco rechaza desde la actualización
del 29/10/2026.

## El problema

Prinex genera ficheros `pain.008.001.02` con direcciones estructuradas que
incluyen `<BldgNm>`, un campo que no existe en esa versión del estándar. El
banco valida contra el XSD y rechaza el fichero:

```
cvc-complex-type.2.4.a: Se ha encontrado contenido no válido a partir del elemento 'BldgNm'
```

## Qué hace la herramienta

1. Reescribe cada `<PstlAdr>` al formato que el banco ya aceptaba:
   `<Ctry>` + dos `<AdrLine>` (calle y número / CP, población y provincia).
2. Opcionalmente corrige `D&aposURGELL` → `D'URGELL` y los CP de 4 cifras (`8010` → `08010`).
3. **Comprueba antes de permitir la descarga** que:
   - los IBAN, importes, mandatos y EndToEndId son idénticos al original;
   - `NbOfTxs` y `CtrlSum` cuadran con las operaciones;
   - ninguna dirección contiene campos no permitidos;
   - el fichero valida contra el XSD oficial, si está en `schemas/`.
4. No guarda nada: los ficheros se procesan en memoria.

Es una solución **temporal** hasta que Prinex corrija el generador.

## Uso (Contabilidad)

1. Abrir la URL de la app.
2. Arrastrar uno o varios XML generados por Prinex.
3. Si aparece en verde «listo para enviar al banco», descargar el fichero `_CORREGIDO.xml`
   (o el ZIP con todos) y subirlo a la banca electrónica.
4. Si aparece en rojo, **no enviar** y avisar a TIC.

## Desarrollo local

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    ·   macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
streamlit run app.py
```

## Estructura

```
app.py                      Interfaz Streamlit
sepa_fix.py                 Lógica de corrección y controles de integridad
schemas/                    XSD oficiales (opcional)
tests/                      Tests con un fichero anonimizado
.streamlit/config.toml      Límite de subida y tema
.github/workflows/tests.yml Tests automáticos en cada push
```

> **Nunca subas remesas reales al repositorio**: contienen IBAN y NIF de
> inquilinos. El `.gitignore` bloquea los `*.xml` salvo el de `tests/data/`.
