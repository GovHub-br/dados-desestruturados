# Especificação da mudança — Título por tabela e fim da fusão de tabelas

## Comportamento esperado

Para a página 8 da ABECIP (jun/2026), a extração produz três tabelas, de 10, 11 e
12 linhas, com o cabeçalho "Agentes | Posição: JUN/2026 … | Posição: ano 2026 …",
cada uma com `section_title` "4 - Construcao", "5 - Aquisicao" e "6 - Aquisicao e
Construcao". Nenhuma linha de cabeçalho aparece como linha de dados.

## Requisitos funcionais

- **RF1 — Título da tabela.** Em `extract_tables`, a seção da tabela é o título mais
  próximo **acima** dela (na vertical) que se sobrepõe a ela na horizontal. Se não
  houver título acima, vale a regra anterior (maior sobreposição horizontal).
- **RF2 — Escopo.** RF1 vale só para tabelas. `blocks`, `metrics` e `charts` seguem
  com a regra anterior: `nearest_section` e `resolve_section_for_item` recebem
  `closest_above=False` por padrão.
- **RF3 — Sem fusão entre tabelas empilhadas.** Dois fragmentos da **mesma página** com
  uma seção entre eles nunca são fundidos. Continuação entre páginas não muda.
- **RF4 — Cabeçalho.** Um cabeçalho lembrado só é aplicado a uma tabela de **mesma
  seção e mesma largura**. O atalho "só pela largura" deixa de existir.
- **RF5 — Superfície.** Nenhuma mudança em `docling_runtime/`, `requirements.txt` nem
  nos patches de GPU. A API do runner e o contrato HTTP seguem iguais.

## Requisitos não funcionais

- Determinístico: mesma entrada, mesma saída.
- Sem dependência nova e sem custo de tempo mensurável por documento.
- Reversível por `atualizar-runner.sh main` no Mac Studio e por `git revert`.

## Critérios de aceite

Ver [ACCEPTANCE.md](ACCEPTANCE.md). Resumo: testes de unidade verdes; replays sobre o
corpus gravado sem trocar cabeçalhos; reextração dos mesmos PDFs no Mac Studio com
cada diferença conferida contra o PDF e nenhuma pior; decisão final por comparação com a
extração antiga. O layout signature atual não é critério: foi escrito sobre a extração
antiga.
