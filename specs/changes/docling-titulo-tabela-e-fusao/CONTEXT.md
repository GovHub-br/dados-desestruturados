# Contexto da mudança — Título por tabela e fim da fusão de tabelas no `docling_pipeline`

- Status: em validação (diagnóstico e protótipo em 2026-10-19; reextração no Mac Studio pendente)
- Branch: `fix/docling-titulo-tabela-e-fusao`, criada a partir de `origin/main` em `c017c16`.
- Ferramentas, linhas de base e variantes testadas: [eval/docling_tabelas/](../../../eval/docling_tabelas/README.md).

## Problema

Na página 8 do relatório mensal da ABECIP há três tabelas empilhadas, cada uma com
título próprio dentro da imagem ("4 - Construção", "5 - Aquisição", "6 - Aquisição
e Construção"). A extração do Docling mostra o seguinte, em 11 de 11 execuções
da ABECIP analisadas:

1. Os três títulos **são capturados** como seções (`sections.jsonl`), às vezes
   com erro de OCR ("Construgao"). Nenhuma tabela fica ligada a eles: todas
   recebem o título largo da página ("Indicadores do Crédito Imobiliário SBPE").
2. Em 7 das 11 execuções as três tabelas saem **fundidas em uma só** (32 a 42
   linhas). O cabeçalho verdadeiro de cada uma vira linha de dados e a tabela
   ganha o cabeçalho "Anos / UnidadesFinanciadas" de outra tabela da página 7.
   Nas outras 4 execuções elas saíram separadas, mas só porque o OCR escreveu
   os cabeçalhos de forma ligeiramente diferente.
3. O mesmo defeito de cabeçalho trocado existe hoje fora da ABECIP: Gerdau (1
   tabela) e Vale (4 tabelas, página 37).

Causas, todas em `docling_pipeline/extractors/`:

- `common.nearest_section` ordena por sobreposição horizontal primeiro; o título
  largo da página sempre vence o subtítulo estreito colado na tabela.
- `tables._propagate_headers` copia o cabeçalho da última tabela de **mesma
  largura** quando o cabeçalho próprio "parece dado" (a regra extrai todos os
  dígitos: "Posicao: JUN/2026…" vira "dado" por conter um ano).
- `tables._merge_pair` funde fragmentos de colunas idênticas sem ver que há um
  título entre eles.

Prova: o `table_id` da tabela fundida é o hash dos itens 97, 99 e 101 do Docling,
intercalados com as seções 96, 98 e 100 (os três títulos).

## Objetivo

Cada tabela empilhada sai separada, com o próprio cabeçalho e ligada ao título
que está logo acima dela, sem piorar as extrações que hoje estão corretas.

## Fora de escopo

- Blocos, métricas e gráficos: continuam com a regra atual de associação à seção.
- OCR: perda de acentos e caracteres trocados ("Posigao", "Milh6es", "0UT/2025").
- Etapa de LLM da extração de texto e qualquer mudança em `docling_runtime/`.
- Regenerar o layout signature da ABECIP (consequência desta mudança, ver riscos).

## Vocabulário e invariantes

- **Seção**: título detectado em `sections.jsonl`. **Título da tabela**: a seção
  associada a ela (`section_title`, `title_canonical`).
- **Item do Docling**: cada tabela devolvida pelo Docling, antes da propagação de
  cabeçalho e da fusão.
- A resolução determinística seleciona tabelas por **arquivo, linha e coluna**; o
  título da tabela é metadado e contexto de fallback, não seletor.
- `sections.jsonl` não muda. `nearest_section` mantém o comportamento atual quando
  `closest_above` não é passado.

## Riscos e dependências

- O layout signature atual da ABECIP aponta para `tables/table005.json` com
  `faixas_linhas` fixas (1–10, 12–22, 24–35) e cabeçalhos "nas linhas 0, 11 e 23".
  Foi escrito sobre a tabela fundida e **precisa ser regenerado** após a mudança.
- A regra de cabeçalho por (título, largura) pode perder uma propagação legítima
  em tabela que continua na página seguinte sob outro título. Não é mensurável
  sem reextrair os PDFs; por isso a validação final é a reextração no Mac Studio.
- 20 das 50 mudanças de título fora da ABECIP não foram inspecionadas.
- A variante com regra de "dado" mais estrita (B1) foi descartada: trocaria o
  cabeçalho de tabelas hoje corretas (Santander ×4, Petrobras ×2). Ver `DECISIONS.md`.
