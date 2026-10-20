# Pendências do `docling_pipeline` para análise futura

Achadas na reextração de 2026-10-20 ([RESULTADO_REEXTRACAO.md](RESULTADO_REEXTRACAO.md)). Ficam **fora do escopo atual** (ABECIP e construtoras). Dados para reproduzir: `extracoes/{antigo,novo,pdfs}/` e [comparacao_extracoes.md](comparacao_extracoes.md).

| # | Problema | Onde | Evidência | Origem |
| --- | --- | --- | --- | --- |
| P1 | **Blocos de tabela perdidos.** Só os rótulos das linhas vêm (como texto); os números não estão em nenhum arquivo | Gerdau p. 24 (2T26, 1T26) e p. 25 (6M25); mesmo resultado na extração antiga | Valores como `1.351.937` e `2.907.909` ausentes da extração; presentes na camada de texto do PDF. O extrator converte todo `TableItem` e o log mostra 23 itens: a perda é do Docling (provável falha de detecção de layout em blocos com faixa azul e sem grade, **não confirmada**) | Docling |
| P2 | **Fusão de tabelas entre páginas** | Gerdau p. 24+25 (2T25 + 6M26, 26 linhas); Petrobras TABELA 23+24, 27+28, 29+30 | Mesmas colunas, alinhadas, em páginas seguidas: a regra de continuação cola, mesmo com título novo no topo da 2ª. A correção atual só impede a fusão na mesma página | `tables._merge_pair` |
| P3 | **Título trocado pelo da tabela vizinha** | Gerdau p. 24 ("Margem Bruta", rótulo de linha); PRIO p. 12 ("Resultados do Período", título da tabela de cima) | O título mais próximo acima pode estar longe ou ser de outra tabela. Antes vinha o título da página | `closest_above` (esta branch) |
| P4 | **Cabeçalho genérico** (`0` a `8`) | Vale p. 19 | Sem cabeçalho reconhecido pelo Docling. Antes vinha "US$/t \| 2T26 \| 2T25…" (unidade errada, períodos certos por coincidência) | Remoção do atalho por largura (esta branch) |
| P5 | **Título que só existe como célula ou partido em duas seções** | Vale p. 20 (título errado nos dois lados); Renner p. 16 ("EBITDA Total / Ajustado") | Sem seção própria para o título da tabela | Docling |

Hipóteses para quando for tratado (nenhuma testada):

- **P1:** despejar no Mac os clusters de layout das p. 24 e 25; testar resolução maior da página ou outro modelo de layout; ou fallback que reconstrua a tabela pela camada de texto do PDF.
- **P2:** não fundir entre páginas quando a 2ª parte começa com uma linha de título (ex.: "RESULTADOS 6M26").
- **P3:** só aceitar o título mais próximo quando estiver a poucos pontos acima da tabela; fora disso, manter a regra antiga.
