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

## D5 — Layout signature e regras determinísticas não são critério de aceite

A versão inicial do aceite exigia que as regras determinísticas do signature
continuassem com o mesmo resultado (A8). Isso usa a extração antiga como gabarito. O
signature da ABECIP foi escrito sobre a tabela fundida (`table005.json`, faixas de
linhas fixas); uma extração que separa as três tabelas corretamente não casa com ele, e
a falha seria lida como regressão quando é melhoria. O mesmo vale para qualquer outra
linha de base construída sobre a extração antiga.

O critério passa a ser só a comparação do conteúdo extraído com o PDF: cada diferença
entre a extração nova e o controle é classificada como melhor, neutra ou pior, e só
"pior" reprova (A8 a A10). Por coerência, a exigência de `schema` e `rows` idênticos
fora do conjunto esperado também saiu (A9): uma diferença pode ser justamente uma
fusão corrigida em outra empresa. Reescrever o signature da ABECIP, se a mudança for
adotada, é tarefa posterior.

## D4 — Ferramentas e linhas de base dentro do repositório

Os dados em que os scripts se apoiam (`resultados*`, `airflow/state/*`) estão no
`.gitignore`. Por isso as linhas de base (JSON) e os scripts ficam em
`eval/docling_tabelas/`, para a comparação poder ser repetida em outra máquina ou
sessão. Os scripts em `historico/` documentam como se chegou aqui e não fazem parte do
fluxo de validação.

## D6 — Escopo desta rodada: ABECIP e construtoras

Na reextração de 15 PDFs (2026-10-20), ABECIP e construtoras ficaram resolvidas e sem piora. As 3 pioras (Gerdau p. 24, PRIO p. 12, Vale p. 19) e os limites que a correção não cobre (blocos perdidos pelo Docling, fusão entre páginas) estão em outras empresas. O usuário decidiu documentá-los para análise futura em `eval/docling_tabelas/PENDENCIAS.md`, sem refinar a regra agora. A reprovação de A10 fica registrada como medida, não como bloqueio.
