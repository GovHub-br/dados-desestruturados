# Heurísticas de Extração

O projeto usa heurísticas pequenas e explícitas, concentradas principalmente em `helpers/` e `extractors/`.

## Títulos

`looks_like_title()` considera como título:

- labels do Docling como `title` e `section_header_level_*`;
- textos curtos com prefixos como `comparativo`, `resumo`, `indicadores`;
- textos curtos em caixa alta ou title case com poucas palavras.

Isso mostra uma decisão importante: o projeto não confia cegamente em um único sinal.
Ele combina label, forma textual e comprimento.

## Papéis textuais

`_infer_block_role()` classifica blocos como:

- `title`
- `field_label`
- `field`
- `paragraph`
- `narrative`
- `note`
- `list_item`

Essa classificação não pretende ser ontologicamente perfeita. Ela existe para apoiar decisões posteriores:

- o que pode virar campo;
- o que deve virar narrativa;
- o que deve ser ignorado numa extração específica;
- o que merece entrar como candidato textual para LLM.

## Números e unidades

`parse_flexible_number()` tenta lidar com:

- formatos pt-BR e en-US;
- milhares com ponto;
- percentuais com vírgula;
- escalas como `mil`, `mi`, `bi`, `million`, `billion`.

### O que a heurística evita

O parser tenta não confundir:

- períodos como `4T 2025`;
- rótulos misturados com números;
- colunas essencialmente categóricas;
- milhares com ponto versus decimais com ponto, dependendo do contexto.

`infer_unit_hint()` acrescenta pistas como:

- `currency_brl`
- `billions`
- `millions`
- `percent`

## Extração de métricas curtas

`maybe_metric_from_text()` detecta linhas curtas com valor embutido, por exemplo:

- `Receita líquida 2,4 bi`
- `Margem EBITDA 18,2%`

Ela tenta separar:

- rótulo;
- valor numérico;
- valor textual bruto.

Esse extractor é deliberadamente conservador:

- ignora textos muito longos;
- ignora sequências quase só numéricas;
- usa o último match numérico como candidato ao valor principal.

Funciona bem para cartões, bullets e frases compactas, mas não tenta resolver narrativas longas sozinho.

## Resolução de contexto

A associação de um item a uma seção segue uma ordem de preferência:

1. grafo estrutural do Docling;
2. ordem de leitura;
3. bbox e proximidade geométrica.

## Heurística espacial da seção mais próxima

`nearest_section()` usa:

- sobreposição horizontal;
- distância vertical;
- distância entre centros horizontais.

Em termos práticos, a seção "melhor" é a que:

1. está mais alinhada horizontalmente ao item;
2. aparece antes ou na mesma região de leitura;
3. exige o menor salto geométrico.

## Heurísticas como contrato de manutenção

Uma grande vantagem de documentar essas regras é que ajustes futuros ficam mais seguros.
Quando uma saída parecer estranha, você consegue perguntar:

- a falha veio da árvore do Docling;
- a falha veio da classificação do bloco;
- a falha veio do parsing numérico;
- ou a falha veio da associação de contexto.
