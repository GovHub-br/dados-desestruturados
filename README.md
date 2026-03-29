python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida

TO DO: confirmar se não deveria gerar imagens das seções que a pipeline deveria cortar das sections e fazer um comparativo com da vlm (talvez uma vlm específica para selecionar escopos)

TO DO: para cada item granular, ver se o bbox dele está contido em um bbox maior


python3 -m docling_pipeline docling_pipeline/dados.pdf \
  --output-dir ./saida \
  --enable-remote-vlm-assist \
  --remote-api-url SUA_URL \
  --remote-api-runtime generic \
  --remote-api-model SEU_MODELO
