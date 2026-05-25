# Heurísticas de Extração

O projeto usa heurísticas pequenas e explícitas, concentradas principalmente em `helpers/` e
`extractors/`. O objetivo desta página é mostrar não apenas o que cada heurística faz, mas também como
ela aparece no código e qual efeito prático ela produz.

## Títulos

`looks_like_title()` considera como título:

- labels do Docling como `title` e `section_header_level_*`;
- textos curtos com prefixos como `comparativo`, `resumo`, `indicadores`;
- textos curtos em caixa alta ou title case com poucas palavras.

Trecho principal:

```python
def looks_like_title(text: str, label: str) -> bool:
    normalized = normalize_space(text)
    if not normalized:
        return False
    if label in TITLE_LABEL_HINTS:
        return True
    lowered = normalized.lower()
    if len(normalized) <= 140 and any(lowered.startswith(prefix) for prefix in TITLE_PREFIX_HINTS):
        return True
    if len(normalized) <= 120 and (normalized.isupper() or normalized.istitle()) and len(normalized.split()) <= 14:
        return True
    return False
```

Leitura operacional:

1. textos vazios são descartados;
2. labels fortes do Docling têm prioridade;
3. prefixos recorrentes funcionam como pista semântica;
4. forma visual curta, em caixa alta ou title case, funciona como fallback.

Essa heurística mostra uma decisão central do projeto: a pipeline não confia em um único sinal. Ela
combina label estrutural, forma textual e comprimento.

## Papéis textuais

`_infer_block_role()` classifica blocos como:

- `title`
- `field_label`
- `field`
- `paragraph`
- `narrative`
- `note`
- `list_item`

Trecho principal:

```python
def _infer_block_role(text: str, label: str) -> str:
    normalized = normalize_space(text)
    lowered = normalized.lower()
    if not normalized:
        return "empty"
    if looks_like_title(normalized, label):
        return "title"
    if lowered.startswith(("nota", "notas do usuario", "observacao", "observação")):
        return "note"
    if label in {"list_item", "list", "listitem"}:
        return "list_item"
    if ":" in normalized:
        prefix, _sep, suffix = normalized.partition(":")
        if prefix and len(prefix) <= 80 and not suffix.strip():
            return "field_label"
        if prefix and len(prefix) <= 80:
            return "field"
        if suffix and len(normalized) > 160:
            return "narrative"
    if len(normalized) > 200:
        return "narrative"
    return "paragraph"
```

Exemplos práticos:

- `Receita líquida:` tende a virar `field_label`;
- `Receita líquida: R$ 2,4 bi` tende a virar `field`;
- um bloco longo tende a virar `narrative`;
- um item de lista do Docling tende a preservar `list_item`.

Essa classificação não pretende ser ontologicamente perfeita. Ela existe para apoiar decisões
posteriores:

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

Trecho de validação inicial:

```python
if parse_ptbr_percent(text) is not None:
    return parse_ptbr_percent(text)

word_tokens = re.findall(r"[A-Za-zÀ-ÿ]+", scrubbed)
allowed_word_tokens = {"bi", "billion", "mi", "million", "mil"}
if any(token.lower() not in allowed_word_tokens for token in word_tokens):
    return None
```

Esse bloco aplica duas regras importantes:

1. percentuais em formato pt-BR são tratados cedo;
2. textos com palavras semânticas não permitidas são descartados antes de forçar parsing numérico.

Trecho de escala:

```python
if re.search(r"\b(?:bi|billion)\b", working, re.I):
    multiplier = 1_000_000_000.0
elif re.search(r"\b(?:mi|million)\b", working, re.I):
    multiplier = 1_000_000.0
elif re.search(r"\bmil\b", working, re.I):
    multiplier = 1_000.0
```

Efeito prático:

- `2,4 bi` vira `2400000000.0`;
- `3,1 mi` vira `3100000.0`;
- `850 mil` vira `850000.0`.

### O que a heurística evita

O parser tenta não confundir:

- períodos como `4T 2025`;
- rótulos misturados com números;
- colunas essencialmente categóricas;
- milhares com ponto versus decimais com ponto, dependendo do contexto.

Trecho relevante:

```python
if _column_prefers_integer(column_name) and THOUSANDS_INTEGER_RE.fullmatch(cleaned):
    cleaned = cleaned.replace(".", "")
elif "," in cleaned and "." in cleaned:
    if cleaned.rfind(",") > cleaned.rfind("."):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
```

Esse trecho existe para impedir normalizações agressivas demais em colunas ambíguas.

`infer_unit_hint()` acrescenta pistas como:

- `currency_brl`
- `billions`
- `millions`
- `percent`

Trecho principal:

```python
def infer_unit_hint(text: str) -> Optional[str]:
    for pattern, unit in UNIT_PATTERNS:
        if pattern.search(text):
            return unit
    return None
```

`infer_unit_hint()` não recalcula o número. Ela apenas registra uma pista semântica adicional para o
consumidor posterior.

## Extração de métricas curtas

`maybe_metric_from_text()` detecta linhas curtas com valor embutido, por exemplo:

- `Receita líquida 2,4 bi`
- `Margem EBITDA 18,2%`

Ela tenta separar:

- rótulo;
- valor numérico;
- valor textual bruto.

Trecho principal:

```python
compact = normalize_space(text)
if not compact or len(compact) > 80:
    return None

if re.fullmatch(r"[\d\s/.,-]+", compact):
    return None

number_matches = list(re.finditer(r"(?:R\$\s*)?[-+]?\d[\d.,]*(?:\s*(?:bi|mi|mil|%))?", compact, flags=re.I))
```

Leitura operacional:

1. a linha é compactada;
2. linhas longas demais são descartadas;
3. linhas sem rótulo textual são descartadas;
4. a função procura trechos que pareçam valores.

Trecho de separação entre rótulo e valor:

```python
last = number_matches[-1]
value_text = last.group(0).strip()
value_numeric = parse_flexible_number(value_text)
label_part = normalize_space((compact[: last.start()] + compact[last.end() :]).strip(" :-|"))
```

Isso revela a regra central da heurística: o valor principal é o último candidato numérico da linha, e
o restante vira o rótulo textual.

Esse extractor é deliberadamente conservador:

- ignora textos muito longos;
- ignora sequências quase só numéricas;
- usa o último match numérico como candidato ao valor principal.

Funciona bem para cartões, bullets e frases compactas, mas não tenta resolver narrativas longas
sozinho.

## Resolução de contexto

A associação de um item a uma seção segue uma ordem de preferência:

1. grafo estrutural do Docling;
2. ordem de leitura;
3. bbox e proximidade geométrica.

Trecho principal:

```python
if item_parent and item_parent in sections_by_self_ref:
    return sections_by_self_ref[item_parent]

if item_self:
    for section in sections:
        if item_self in section.child_refs:
            return section

return nearest_section(...)
```

A lógica da função é:

1. primeiro usar vínculo estrutural explícito;
2. depois usar vínculo inverso por `child_refs`;
3. só então aplicar fallback geométrico.

Essa prioridade é importante porque o projeto tenta preservar a estrutura original antes de recorrer à
proximidade visual.

## Heurística espacial da seção mais próxima

`nearest_section()` usa:

- sobreposição horizontal;
- distância vertical;
- distância entre centros horizontais.

Trecho de score:

```python
def _section_match_score(anchor: BoundingBox, section_bbox: BoundingBox) -> tuple[float, float, float]:
    vertical_distance = _bbox_vertical_distance(anchor, section_bbox)
    horizontal_overlap = _bbox_horizontal_overlap(anchor, section_bbox)
    horizontal_distance = _bbox_horizontal_distance(anchor, section_bbox)
    return (-horizontal_overlap, vertical_distance, horizontal_distance)
```

Trecho de seleção:

```python
return min(with_bbox, key=lambda section: _section_match_score(anchor_bbox, section.bbox))
```

Em termos práticos, a seção "melhor" é a que:

1. está mais alinhada horizontalmente ao item;
2. aparece antes ou na mesma região de leitura;
3. exige o menor salto geométrico.

Não é apenas "a caixa mais próxima". A heurística tenta preservar uma leitura humana plausível do
layout.

## Heurísticas como contrato de manutenção

Uma grande vantagem de documentar essas regras é que ajustes futuros ficam mais seguros.
Quando uma saída parecer estranha, você consegue perguntar:

- a falha veio da árvore do Docling;
- a falha veio da classificação do bloco;
- a falha veio do parsing numérico;
- ou a falha veio da associação de contexto.

Exemplo de pontos concretos de inspeção:

```python
role_hint = _infer_block_role(text, label)
section = nearest_section(sections, page_number=page_number, anchor_bbox=bbox)
value_numeric = parse_flexible_number(value_text)
```

Se a saída final parecer errada, o ponto de investigação normalmente está em uma destas três camadas:

- classificação textual;
- resolução de contexto;
- parsing numérico.
