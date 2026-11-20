# Bundled sample attribution

This package bundles a reduced, offline copy of three Ecuadorian open-data
sources. The data keeps the license of its publisher (Creative Commons
Attribution); the code of this project is MIT-licensed.

## SRI - Recaudacion de impuestos

- Publisher: Servicio de Rentas Internas (SRI)
- URL: https://descargas.sri.gob.ec/download/datosAbiertos/sri_recaudacion_<YYYY>.csv
- License: Creative Commons Attribution (CKAN `license_id: cc-by`)
- Modification: rows aggregated to province grain; `VALOR_RECAUDADO` summed to
  cents; canton, `GRAN_CONTRIBUYENTE` and `CODIGO_OPERA_FAMILIA` dropped; values
  written as UTF-8 with comma decimals and gzip (mtime 0).

## BCE - Cuentas Nacionales Trimestrales desagregadas

- Publisher: Banco Central del Ecuador (BCE)
- URL: https://www.datosabiertos.gob.ec/dataset/7d5ad4b3-a8f7-42d9-8103-81336a592ea6
- License: Creative Commons Attribution (CKAN `license_id: cc-by`)
- Modification: none; the upstream bytes are bundled verbatim inside a gzip
  container.

## INEC - Indice de Precios al Consumidor (December 2024 vintage, base 2014 = 100)

- Publisher: Instituto Nacional de Estadistica y Censos (INEC)
- URL: https://www.ecuadorencifras.gob.ec/indice-de-precios-al-consumidor-2024/
- License: Creative Commons Attribution 4.0 International (CC BY 4.0)
- Modification: the twelve index CSVs are repacked verbatim into one flat ZIP.

`SAMPLE_MANIFEST.json` records the sha256 of every bundled file and the sha256
of the upstream file it was derived from.
