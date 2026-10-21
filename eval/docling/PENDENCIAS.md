# Pendências do `docling_pipeline` para análise futura

Protocolo para medir qualquer correção: [README.md](README.md).

Achadas na reextração de 2026-10-20 ([resultado](resultados/2026-10-titulo-tabela-fusao/RESULTADO.md)). Ficam **fora do escopo atual** (ABECIP e construtoras). Dados para reproduzir: `extracoes/{antigo,novo,pdfs}/` e [comparacao_extracoes.md](resultados/2026-10-titulo-tabela-fusao/comparacao_extracoes.md).

| # | Problema | Onde | Evidência | Origem |
| --- | --- | --- | --- | --- |
| P1 | **Blocos de tabela perdidos.** Só os rótulos das linhas vêm (como texto); os números não estão em nenhum arquivo | Gerdau p. 24 (2T26, 1T26) e p. 25 (6M25); mesmo resultado na extração antiga | Valores como `1.351.937` e `2.907.909` ausentes da extração; presentes na camada de texto do PDF. O extrator converte todo `TableItem` e o log mostra 23 itens: a perda é do Docling (provável falha de detecção de layout em blocos com faixa azul e sem grade, **não confirmada**) | Docling |
| P2 | **Fusão de tabelas entre páginas** | Gerdau p. 24+25 (2T25 + 6M26, 26 linhas); Petrobras TABELA 23+24, 27+28, 29+30 | Mesmas colunas, alinhadas, em páginas seguidas: a regra de continuação cola, mesmo com título novo no topo da 2ª. A correção atual só impede a fusão na mesma página | `tables._merge_pair` |
| P3 | **Título trocado pelo da tabela vizinha** | Gerdau p. 24 ("Margem Bruta", rótulo de linha); PRIO p. 12 ("Resultados do Período", título da tabela de cima) | O título mais próximo acima pode estar longe ou ser de outra tabela. Antes vinha o título da página | `closest_above` (esta branch) |
| P4 | **Cabeçalho genérico** (`0` a `8`) | Vale p. 19 | Sem cabeçalho reconhecido pelo Docling. Antes vinha "US$/t \| 2T26 \| 2T25…" (unidade errada, períodos certos por coincidência) | Remoção do atalho por largura (esta branch) |
| P5 | **Título que só existe como célula ou partido em duas seções** | Vale p. 20 (título errado nos dois lados); Renner p. 16 ("EBITDA Total / Ajustado") | Sem seção própria para o título da tabela | Docling |
| P6 | **Tabela truncada**: só o começo vem; o resto some | Gerdau p. 21 (balanço do PASSIVO: 15 de ~40 linhas; totais `17.980.274`, `53.734.748` e `81.972.713` ausentes) | Igual na extração antiga. Faltam o passivo não circulante e o patrimônio líquido | Docling |
| P7 | **Tabela malformada com linha perdida**: 3 subtabelas empilhadas coladas, células coladas (`'203,0 (771,7)'`) e a linha "Lucro Líquido Operacional (NOPLAT)" (`66,3 97,1 292,4 263,8 137,6`) ausente | MGLU p. 18 (Anexo V, `table018`, 44 linhas) | Os títulos das subtabelas são linhas de cabeçalho, não seções, então nada separa as tabelas | Docling + `_merge_pair` |
| P8 | **Gráficos coletados só em parte**: em barras empilhadas vem uma série só (ex.: Riva sim, Direcional e totais não), e páginas com vários gráficos perdem alguns | Direcional p. 2–3; Itaú p. 4, 7, 8, 9, 10; MGLU p. 20–21; Renner p. 6, 7, 9, 10, 12, 14, 16, 19; Santander p. 8–9; Tenda p. 4 | Os valores dos gráficos ficam em `charts/*/points.json`; comparados com os rótulos do PDF, faltam séries | Extração de gráficos (VLM) |
| P9 | **Primeira linha de dados absorvida como cabeçalho** (o dado não se perde: fica no `schema`) | Gerdau p. 22 ("RECEITA LÍQUIDA DE VENDAS"); PRIO p. 16 ("Saldo em 31 de dezembro de 2025") | O `schema` traz valores (`Ativo.610.400`) | Docling |

## Como se chegou nisso (análise de cobertura, 2026-10-20)

`scripts/analisar_cobertura.py` compara, por página, os números da camada de texto do PDF com os da extração (tabela, texto, gráfico ou ausente). Relatórios: [cobertura_novo.md](resultados/2026-10-titulo-tabela-fusao/cobertura_novo.md) e [cobertura_antigo.md](resultados/2026-10-titulo-tabela-fusao/cobertura_antigo.md). Cobre os 30 PDFs (15 extrações novas e as 15 antigas sem reextração). Teste de controle: acusa a Gerdau p. 24 e 25. Regressão: os mesmos 416 números ausentes antes e depois, página a página. **ABECIP (11 meses), Cury, Pacaembu e Plano&Plano: nenhuma tabela perdida.** Ponto cego: tabela em imagem sem camada de texto não é medida (a CSN p. 3, que é imagem, foi coletada por OCR); as páginas com imagem grande e sem tabela foram olhadas por amostra (capas, divisores, QR, gráficos).

Hipóteses para quando for tratado (nenhuma testada):

- **P1:** despejar no Mac os clusters de layout das p. 24 e 25; testar resolução maior da página ou outro modelo de layout; ou fallback que reconstrua a tabela pela camada de texto do PDF.
- **P2:** não fundir entre páginas quando a 2ª parte começa com uma linha de título (ex.: "RESULTADOS 6M26").
- **P6:** só o começo da tabela foi reconhecido; pode ter a mesma causa de P1 (não verificado). O mesmo despejo de layout da p. 21 ajudaria a decidir.
- **P7:** não fundir fragmentos cujas colunas têm cabeçalho repetido no meio das linhas (ex.: uma linha "RECONCILIAÇÃO DO …" dentro da tabela).
- **P3:** só aceitar o título mais próximo quando estiver a poucos pontos acima da tabela; fora disso, manter a regra antiga.
