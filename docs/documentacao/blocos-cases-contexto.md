# Blocos, Cases e Contexto

## `blocks`

`blocks` é a camada textual base da pipeline. Ela preserva texto, papel inferido, posição e relações nativas do Docling.

Campos importantes:

- `text`
- `role_hint`
- `section_id`
- `section_title`
- `parent_block_id`
- `self_ref`
- `parent_ref`
- `child_refs`

## Como `blocks` apoia o restante da pipeline

`blocks` não é apenas uma saída final. Ele também funciona como camada de serviço para outras etapas:

- `cases` depende diretamente dele;
- `text_candidates` parte dele;
- a inspeção de erros estruturais quase sempre começa por ele.

Por isso vale pensar `blocks` como uma "malha textual canônica" do documento processado.

## `cases`

`cases` é uma consolidação auxiliar por seção, derivada de `sections` + `blocks`.

Ela tenta:

- agrupar blocos da mesma seção;
- recuperar pares `campo: valor`;
- juntar `field_label` com o próximo bloco compatível;
- acumular narrativa longa em `narrative_blocks`.

## Lógica de consolidação de `cases`

O extractor percorre os blocos de cada seção ordenados por `order_index`.
Durante esse percurso, ele aplica decisões diferentes por `role_hint`:

### `field_label`

Quando encontra um bloco que parece apenas um rótulo, ele tenta anexar o próximo bloco compatível como valor.

### `field`

Quando o texto já vem no formato `campo: valor`, ele extrai o par diretamente.

### `paragraph`, `narrative`, `note`, `list_item`

Esses conteúdos são preservados em `narrative_blocks` para que a seção retenha sua parte descritiva.

## `field_map` e repetição de chaves

Quando a mesma chave aparece mais de uma vez, `_append_field()` transforma o valor em lista.
Isso evita perder informação em seções onde um campo pode aparecer repetidamente.

## Resolução de seção dos blocos

Na consolidação, `_resolve_block_section()` tenta:

1. usar `parent_ref` se ele aponta para uma seção;
2. verificar se `self_ref` aparece em `child_refs` de alguma seção;
3. subir pela cadeia de pais;
4. cair no `section_id` já resolvido anteriormente como fallback.

## Por que essa camada existe

Nem tudo em um PDF cabe em um schema fixo logo de primeira. `cases` funciona como camada intermediária
para exploração semiestruturada antes de um mapeamento mais rígido.

## Quando preferir `cases` em vez de `blocks`

Use `cases` quando a pergunta for mais próxima de:

- "quais campos e narrativas esta seção contém?"

Use `blocks` quando a pergunta for mais próxima de:

- "quais itens exatos o Docling expôs e em que ordem?"

Essa diferença parece pequena, mas muda bastante a ergonomia de consumo.
