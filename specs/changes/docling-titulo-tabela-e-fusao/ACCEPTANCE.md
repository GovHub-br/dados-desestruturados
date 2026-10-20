# Aceite — Título por tabela e fim da fusão de tabelas

Preencha cada linha com data, evidência (comando + saída relevante) e resultado. Um
item só passa com evidência. "Mac" indica que o runner do Mac Studio está na branch
desta mudança; "controle" indica o runner no `main`.

## Evidências de validação

| # | Verificação | Como verificar | Req. | Evidência | Resultado |
| --- | --- | --- | --- | --- | --- |
| A1 | Testes de unidade | `pytest tests/unit` → 285 passam; `ruff check src tests/unit scripts/validate_repository_structure.py` limpo | RF1–RF4 | 2026-10-19, 285 passed, ruff ok | ✅ |
| A2 | Cada teste pega seu defeito | Reintroduzir cada defeito numa cópia do código; o teste correspondente falha | RF1, RF3, RF4 | 2026-10-19, 3 mutantes, todos detectados | ✅ |
| A3 | Replay ABECIP | `eval/docling_tabelas/scripts/abecip_meses.py`: código antigo reproduz as 7 fusões; código novo gera 3 tabelas por mês com título e cabeçalho certos | RF1, RF3 | 2026-10-19, 7 de 7 meses | ✅ |
| A4 | Replay Gerdau/Vale | `gerdau_vale.py`: código antigo reproduz o cabeçalho trocado nas 5 tabelas; o novo mantém o verdadeiro | RF4 | 2026-10-19, 5 de 5 | ✅ |
| A5 | Replay do corpus | `replay_corpus_secoes.py` e `replay_propagacao_cabecalho.py`: 0 de 322 cabeçalhos trocados | RF4 | 2026-10-19, 0 de 322 | ✅ |
| A6 | Reextração ABECIP | Mac: reextrair os PDFs de ABECIP dos 7 meses fundidos; `tables/` traz 3 tabelas na página das modalidades, com `section_title` correto | RF1, RF3 | | |
| A7 | Reextração Gerdau/Vale | Mac: a tabela "DEMONSTRAÇÃO DO RESULTADO" (Gerdau, p. 22) e as 4 da p. 37 da Vale mantêm o cabeçalho verdadeiro | RF4 | | |
| A8 | Empresas com signature | Mac vs controle, Cury, Direcional, Pacaembu e Plano&Plano: `schema` e `rows` de todas as tabelas idênticos; só `section_title`/`title_canonical` podem mudar. Regras determinísticas do signature com o mesmo resultado | RF2, RF4 | | |
| A9 | Demais empresas | Mac vs controle: `schema` e `rows` idênticos fora do conjunto esperado (A6, A7); `blocks/`, `metrics/` e `charts/` idênticos | RF2 | | |
| A10 | Títulos alterados | Amostra de pelo menos 30 mudanças de `section_title` revisada pelo conteúdo da tabela: melhores ou neutras, nenhuma pior | RF1 | | |
| A11 | Desempenho | Tempo por PDF do Mac dentro de 5% do controle | RF5 | | |
| A12 | Runner de volta ao `main` | `git -C ~/docling-runner/repo branch --show-current` → `main` e `/healthz` ok | — | | |

## Critério de decisão (etapa 7)

A nova versão **fica** se A6 a A9 passarem sem exceção e A10 não encontrar nenhuma
mudança pior. Qualquer alteração de `schema` ou `rows` fora do conjunto esperado, ou
qualquer título pior, reprova e a branch volta para análise. Em caso de dúvida, o
controle em `main` prevalece, porque ele é a mesma máquina e as mesmas bibliotecas.

## Resultado

_A preencher ao final das etapas 5 e 6._
