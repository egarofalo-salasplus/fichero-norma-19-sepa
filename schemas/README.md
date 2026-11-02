# Esquemas XSD oficiales (opcional, recomendado)

Si colocas aquí el XSD oficial, la app valida cada fichero corregido contra él
antes de permitir la descarga. El nombre debe coincidir con la versión:

- `pain.008.001.02.xsd` (adeudos SEPA / norma 19)
- `pain.001.001.03.xsd` (transferencias SEPA / norma 34)

Descárgalos de https://www.iso20022.org (Catalogue of messages → Archive) o
pídeselos al banco: suelen venir en su guía de implementación.
Sin XSD la app hace igualmente la comprobación de estructura de direcciones,
que es la causa del rechazo.
