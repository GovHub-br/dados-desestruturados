# Resultado da reextração no Mac Studio: Docling antigo × Docling da branch

- Data: 2026-10-20
- Código testado: branch `fix/docling-titulo-tabela-e-fusao`, commit `60bc1f1`, runner do Mac Studio nesse commit (conferido por `rev-parse` e `/healthz`).
- Referência: a extração mais recente de cada PDF que já estava no MinIO (`execucoes/…/extraction`).
- Escopo: 15 PDFs, um por empresa (os outros trimestres e meses da ABECIP são muito parecidos e ficaram de fora). 15 de 15 extrações concluídas sem falha, 49,7 min no runner.
- Detalhe tabela a tabela: [comparacao_extracoes.md](comparacao_extracoes.md).

## Veredito

**Dentro do escopo atual (ABECIP e construtoras): resolvido, sem pioras.** ABECIP: a tabela fundida virou 3 tabelas corretas. Cury: sem mudança. Direcional, Pacaembu, Plano&Plano e Tenda: só trocaram título, todos para melhor e conferidos no PDF.

**No conjunto dos 15 PDFs: melhorou, com três regressões pequenas**, todas fora do escopo (Gerdau, PRIO, Vale). Pelo critério do [ACCEPTANCE.md](../../specs/changes/docling-titulo-tabela-e-fusao/ACCEPTANCE.md) ("qualquer diferença pior reprova"), o conjunto não passa em A10. Por decisão do usuário (D6), isso e os limites encontrados foram registrados em [PENDENCIAS.md](PENDENCIAS.md) para análise futura.

| Tipo de mudança (67 no total) | Quantidade |
| --- | --- |
| Melhor | 62 |
| Neutra | 2 |
| Pior | 3 |

Das 67, 16 trocas de título e 12 divisões ou cabeçalhos foram conferidas **abrindo o PDF**; as demais foram julgadas pelo conteúdo da tabela (título combina com as linhas) e, nas divisões, pela prova de dados abaixo.

## O problema da ABECIP (maio/2026, página 8)

| | Antes | Agora |
| --- | --- | --- |
| Tabelas na página | 1 fundida, 36 linhas | 3, com 10, 11 e 12 linhas |
| Título | "Indicadores do Crédito Imobiliário SBPE" | "4 - Construcao", "5 - Aquisicao", "6-AquisicaoeConstrucao" |
| Cabeçalho | "Anos / UnidadesFinanciadas", de outra tabela; o verdadeiro virou linha de dados | "Agentes \| Posição: MAI/2026 …" em cada uma |
| Linha TOTAL de cada tabela | só a do fim | 5.546,2 / 11.622,5 / 17.168,7 (R$ milhões), iguais ao PDF |

Na página 7 do mesmo PDF, a tabela "1 - SBPE: Evolução do saldo…" também ganhou o título certo (antes recebia o título genérico da página). As tabelas 2 e 3 da página já estavam corretas.

## Provas automáticas (sobre os 15 PDFs)

1. **Nenhuma linha de dados perdida nem inventada.** Nos 23 grupos de tabelas que mudaram além do título, cada linha de dados do antigo existe no novo (como dado, ou como cabeçalho quando o cabeçalho verdadeiro estava como linha de dados), e vice-versa. Resultado: 23 de 23 "dados preservados", 0 alertas. O teste foi validado com casos sintéticos (perda e invenção de linha são detectadas).
2. **Nada fora de tabelas mudou.** `sections`, `blocks`, `metrics`, `cases`, `text_candidates` (nº de linhas) e `charts/` (nº de gráficos) são iguais nos 15 PDFs. Isso também indica que as diferenças vêm do código e não de mudança de bibliotecas desde a extração antiga: o texto de cada célula é idêntico.
3. **Sem mudança:** CSN (12 de 12 tabelas), Cury (6 de 6), Itaú (8 de 8) e Santander (5 de 5) saíram idênticas.

## Resultado por PDF

| PDF | Tabelas | Mudou | Veredito |
| --- | --- | --- | --- |
| ABECIP 2026-05 | 5 → 7 | 1 fundida virou 3; 1 título | Melhor (PDF conferido) |
| CSN, Cury, Itaú, Santander | iguais | nada | Sem mudança |
| Direcional | 4 → 4 | 4 títulos "PRÉVIA OPERACIONAL" viraram "LANÇAMENTOS", "VENDAS CONTRATADAS", "ESTOQUE" e o do glossário | Melhor |
| Pacaembu | 5 → 5 | "Landbank" deixou de herdar o título "Unidades habitacionais entregues" | Melhor (PDF) |
| Plano&Plano | 5 → 5 | "BANCO DE TERRENOS" virou "OBRAS" | Melhor (conteúdo) |
| Tenda | 5 → 5 | "RESULTADOS OPERACIONAIS" virou "LANÇAMENTOS" | Melhor (conteúdo) |
| MGLU | 23 → 26 | "Receita Bruta/Líquida/Lucro Bruto" (3) e as duas DREs da Luizacred (2) separadas; 1 título | Melhor (PDF p. 8) |
| Gerdau | 18 → 20 | "Fluxo de caixa livre" e a reconciliação separadas; "Demonstração do resultado" com o cabeçalho de períodos em vez de "AGÊNCIAS DE RATINGS"; 6 títulos melhores | Melhor, 1 pior |
| Petrobras | 20 → 25 | Tabelas 22/23/25 e 26/27/29/31 separadas; 4 títulos melhores | Melhor, com limite (ver abaixo) |
| PRIO | 11 → 11 | 3 títulos (inclui "丹 PRIC" → "BALANÇO PATRIMONIAL") | Melhor, 1 pior leve |
| Renner | 16 → 16 | "Fluxo de Caixa Livre" certo; 2 títulos neutros | Melhor, 2 neutras |
| Vale | 50 → 63 | "Total Projetos / crescimento / manutenção" separadas (PDF p. 5); as 4 tabelas do Brumadinho/Samarco com título e cabeçalho verdadeiros (PDF p. 37); balanço com cabeçalho certo (p. 20); 18 títulos melhores; mais 9 divisões | Melhor, 1 pior |

## O que piorou

1. **Gerdau, p. 24, bloco "RESULTADOS 2T25".** Título passou de "RESULTADOS POR SEGMENTOS DE NEGÓCIO" (título da página) para "Margem Bruta", que é um rótulo de linha de outro bloco da página, reconhecido pelo Docling como seção. Linhas idênticas. Essa tabela de 26 linhas é, na verdade, dois blocos colados entre páginas (ver "O que a correção não resolve").
2. **PRIO, p. 12, tabela "Estoque de óleo".** Título passou de "DESEMPENHO FINANCEIRO" (seção da página) para "Resultados do Período", que é o título da tabela de cima. A tabela não tem título próprio. Linhas idênticas.
3. **Vale, p. 19, "Demonstrações financeiras simplificadas".** O Docling não reconheceu cabeçalho (colunas `0` a `8`). Antes a tabela vinha com "US$/t \| 2T26 \| 2T25 …": unidade errada, mas nomes de período certos por coincidência da cópia pela largura. Linhas idênticas; só os nomes das colunas de período se perderam.

As causas 1 e 2 são do mesmo tipo: o título mais próximo acima da tabela pode estar longe dela ou pertencer a outra tabela. **Hipótese ainda não testada:** só aceitar o título mais próximo quando ele estiver a poucos pontos acima da tabela e, fora disso, manter a regra antiga. A 3 é efeito da remoção do atalho "cabeçalho pela largura", que também corrigiu os 5 casos de cabeçalho trocado; não tem correção sem trazer o defeito de volta.

Neutras: Renner, "EBITDA Total" → "Ajustado" (o título do PDF é "EBITDA Total / Ajustado", partido em duas seções pelo Docling) e "Investimentos e expansão" → " I nvestimentos".

## O que a correção não resolve

- **Fusão entre páginas.** Petrobras: as tabelas 24, 28 e 30 começam no topo da página seguinte e continuam coladas na anterior (a "TABELA 23" tem 24 linhas e duas linhas "Total"). A correção só impede a fusão de fragmentos da mesma página. Já melhorou (antes eram 48 linhas numa tabela), mas não está resolvido.
- **Gerdau, p. 24 e 25 (igual na extração antiga).** As duas páginas têm 5 blocos de "RESULTADOS" empilhados (2T26, 1T26, 2T25, 6M26, 6M25). O Docling devolveu como tabela só 2: o 2T25 (p. 24) e o 6M26 (p. 25), que a regra de continuação entre páginas colou numa tabela de 26 linhas (linhas 0 a 12 e 13 a 25, cada metade com seu "RESULTADOS …"). Os outros 3 blocos (2T26, 1T26 e 6M25) **não estão em nenhum arquivo da extração**: só os rótulos de linha vieram, como blocos de texto (46 blocos nas p. 24 e 25, iguais nas duas extrações), e nenhum número. O PDF tem camada de texto com os números. O nosso extrator converte todo `TableItem` que recebe e o log mostra 23 itens do Docling, então a perda acontece dentro do Docling (detecção de layout), não no nosso código. A causa exata não foi confirmada, porque a saída bruta do Docling não é gravada.
- **Título que só existe dentro da imagem ou como célula** (ex.: "Estoque de óleo", "Balanço patrimonial") continua não sendo seção; a tabela recebe o título mais próximo, certo ou não. Vale p. 20 tem o título errado nos dois lados.
- **Layout signature da ABECIP:** não foi usado como critério (decisão D5). Ele aponta para a tabela fundida (`table005.json`) e precisa ser reescrito se a mudança for adotada.

## Aceite (ACCEPTANCE.md)

| # | Resultado | Observação |
| --- | --- | --- |
| A6 | ✅ | 1 PDF da ABECIP (o de maio) em vez dos 7; o replay offline cobre os 7 |
| A7 | ✅ | Gerdau p. 22 e Vale p. 37 com cabeçalho verdadeiro |
| A8 | ✅ | Cury sem mudança; Direcional, Pacaembu e Plano&Plano só com títulos melhores; `schema` e `rows` iguais |
| A9 | ✅ | Nenhuma linha de dados perdida; nada fora de tabelas mudou |
| A10 | ❌ | 44 trocas de título só de título: 40 melhores, 2 neutras, **2 piores** (Gerdau p. 24, PRIO p. 12) |
| A11 | não medido | Sem controle em `main` para comparar o tempo |
| A12 | pendente | Runner ainda na branch; voltar com `atualizar-runner.sh main` quando acabar |

Não foi feita a extração de controle em `main`: a prova de dados e a igualdade dos artefatos fora de tabelas já atribuem as diferenças ao código.

## Decisão e próximos passos

Decisão do usuário (2026-10-20): o problema a resolver agora é ABECIP e construtoras, já resolvido; as pioras e os limites das outras empresas vão para [PENDENCIAS.md](PENDENCIAS.md), sem refinar a regra por enquanto. Falta decidir o merge no `main`. O runner do Mac Studio **ainda está na branch**: voltar com `atualizar-runner.sh main` (A12).

## Como repetir

```bash
S=/opt/project/dados-desestruturados/eval/docling_tabelas/scripts
docker exec ocr_airflow_scheduler python $S/baixar_extracoes_antigas.py
docker exec ocr_airflow_scheduler python $S/extrair_lote_runner.py --rotulo novo \
  --filtro data-abecip-2026-05 --filtro cury_2T26 …          # um filtro por PDF
python3 eval/docling_tabelas/scripts/comparar_extracoes.py    # gera comparacao_extracoes.md
```

Os dados brutos ficam em `eval/docling_tabelas/extracoes/` (`antigo/`, `novo/`, `pdfs/`), fora do git.
