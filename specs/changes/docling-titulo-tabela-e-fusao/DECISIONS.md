# Decisões — Título por tabela e fim da fusão de tabelas

## D1 — A regra nova vale só para tabelas (`closest_above`)

`nearest_section` também é usada por `blocks.py`, `metrics.py` e `charts.py`. A
primeira versão do protótipo mudou a regra para todos, mas a medição cobriu apenas
tabelas. Mudar a seção de parágrafos, métricas e gráficos também alteraria `cases/` e
os candidatos de texto, sem evidência. A regra nova entra por parâmetro opcional,
desligado por padrão, e só `extract_tables` o liga.

## D2 — Descartar a regra de "dado" mais estrita (B1)

Tornar `tables._value_is_data_like` mais estrita corrige a ABECIP, mas troca o
cabeçalho de 6 tabelas hoje corretas (Santander ×4, Petrobras ×2) no replay. Hoje elas
estão certas "por sorte": a regra atual trata "2T26 x 1T26" como dado, então nenhum
cabeçalho dessas empresas é memorizado e nada é sobrescrito. Ao corrigir a regra, o
primeiro cabeçalho passa a ser memorizado e os seguintes são sobrescritos. Mesmo na
versão estritamente numérica, só 2 de 5 casos de Gerdau/Vale ficavam certos (nos outros
3 o cabeçalho continuava trocado). A raiz é o atalho que copia cabeçalho só pela
largura; é ele que sai (D3).

## D3 — Lembrar cabeçalho só por (título, largura)

`_propagate_headers` mantinha dois índices: por (título, largura) e só por largura. O
segundo é removido. Só pode **reduzir** substituições de cabeçalho, nunca criar novas.
Risco conhecido e não mensurável offline: perder a propagação de uma tabela que
continua em outra página sob título diferente. A reextração no Mac decide.

## D4 — Ferramentas e linhas de base dentro do repositório

Os dados em que os scripts se apoiam (`resultados*`, `airflow/state/*`) estão no
`.gitignore`. Por isso as linhas de base (JSON) e os scripts ficam em
`eval/docling_tabelas/`, para a comparação poder ser repetida em outra máquina ou
sessão. Os scripts em `historico/` documentam como se chegou aqui e não fazem parte do
fluxo de validação.
