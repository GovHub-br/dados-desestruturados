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
| A6 | Reextração ABECIP | Mac: reextrair os PDFs de ABECIP dos 7 meses fundidos; `tables/` traz 3 tabelas na página das modalidades, com `section_title` correto | RF1, RF3 | 2026-10-20, runner em `60bc1f1`, PDF de maio/2026 (1 dos 7, por decisão do usuário): a tabela fundida de 36 linhas virou 3 de 10, 11 e 12 linhas, títulos "4 - Construcao", "5 - Aquisicao", "6-AquisicaoeConstrucao", TOTAL de cada uma igual ao PDF. Ver `eval/docling_tabelas/RESULTADO_REEXTRACAO.md` | ✅ |
| A7 | Reextração Gerdau/Vale | Mac: a tabela "DEMONSTRAÇÃO DO RESULTADO" (Gerdau, p. 22) e as 4 da p. 37 da Vale mantêm o cabeçalho verdadeiro | RF4 | 2026-10-20: Gerdau p. 22 sem "AGÊNCIAS DE RATINGS", com o cabeçalho de períodos do PDF; Vale p. 37 com os 4 cabeçalhos "US$ bilhão/US$ milhões …" e títulos certos (conferido no PDF) | ✅ |
| A8 | Empresas que têm signature | Mac vs controle, Cury, Direcional, Pacaembu e Plano&Plano: abrir o PDF e comparar cada tabela (`schema`, `rows`, `section_title`). Classificar cada diferença como melhor, neutra ou pior que o controle. **O signature não entra na conta** (ver "Fora do critério") | RF2, RF4 | 2026-10-20, comparado com a extração antiga (sem controle em `main`): Cury 6 de 6 idênticas; Direcional, Pacaembu e Plano&Plano só trocaram títulos, todos melhores; `schema` e `rows` iguais | ✅ |
| A9 | Demais empresas | Mac vs controle: toda diferença de `schema` ou `rows` fora do conjunto esperado (A6, A7) é conferida contra o PDF e classificada como melhor, neutra ou pior. `blocks/`, `metrics/` e `charts/` não deveriam mudar (RF2): qualquer diferença é investigada | RF2 | 2026-10-20: 23 de 23 grupos alterados com "dados preservados" (nenhuma linha de dados perdida ou inventada); `sections`, `blocks`, `metrics`, `cases`, `text_candidates` e nº de gráficos iguais nos 15 PDFs | ✅ |
| A10 | Títulos alterados | Amostra de pelo menos 30 mudanças de `section_title` revisada pelo conteúdo da tabela: melhores ou neutras, nenhuma pior | RF1 | 2026-10-20: 44 mudanças só de título, 14 conferidas no PDF e 30 pelo conteúdo: 40 melhores, 2 neutras, **2 piores** (Gerdau p. 24 "Margem Bruta"; PRIO p. 12 "Resultados do Período"). Além delas, 1 cabeçalho que ficou genérico (Vale p. 19). Ver `eval/docling_tabelas/RESULTADO_REEXTRACAO.md` | ❌ |
| A11 | Desempenho | Tempo por PDF do Mac dentro de 5% do controle | RF5 | Não medido: não houve extração de controle em `main`. Os 15 PDFs levaram 49,7 min no total | — |
| A12 | Runner de volta ao `main` | `git -C ~/docling-runner/repo branch --show-current` → `main` e `/healthz` ok | — | | |

## Critério de decisão (etapa 7)

A nova versão **fica** se A6 e A7 passarem e a comparação pelo conteúdo (A8 a A10) não
encontrar nenhuma diferença **pior** que o controle. Diferença em `schema`, `rows` ou
título que seja melhor ou neutra não reprova: o que importa é se a extração reflete
melhor o PDF, não se ela é igual à antiga. Qualquer diferença pior reprova e a branch
volta para análise. Em caso de dúvida, o controle em `main` prevalece, porque ele é a
mesma máquina e as mesmas bibliotecas.

## Fora do critério: layout signature e regras determinísticas

O layout signature e as regras determinísticas que existem hoje foram escritos sobre a
extração **antiga**. O da ABECIP, por exemplo, aponta para `tables/table005.json`, a
tabela fundida, com `faixas_linhas` fixas e cabeçalhos "nas linhas 0, 11 e 23". Se a
extração nova for melhor e por isso não casar com o signature, quem está desatualizado é
o signature, não a extração. Por isso:

- Nenhum item deste aceite exige que o signature ou as regras determinísticas continuem
  funcionando sobre a extração nova.
- Falha do signature sobre a extração nova **não** reprova a mudança e não conta como
  regressão. O julgamento é só pela comparação do conteúdo extraído com o PDF.
- Se a mudança for adotada, reescrever o signature sobre a extração nova é tarefa
  posterior, fora desta mudança.

## Resultado

Reextração de 15 PDFs (um por empresa) em 2026-10-20: o problema da ABECIP está resolvido e
62 de 67 mudanças são melhores, 2 neutras e 3 piores. Pelo critério acima, A10 reprova
(2 títulos piores) e a branch volta para análise; a decisão entre adotar como está ou
refinar a regra do título está em `eval/docling_tabelas/RESULTADO_REEXTRACAO.md`.
