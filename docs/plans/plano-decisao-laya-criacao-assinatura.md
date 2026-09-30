# Plano 2: Modelo de Decisão (laya) na Criação da Assinatura de Layout

- Status: proposto
- Escopo: DAG 3, `escopo_correcao = criacao_inicial_layout`, geração do `layout_signature_candidato`
- Substitui: **chamada LLM #2** do fallback
- Par: [Plano 1 — Seleção de Artefatos](plano-decisao-laya-selecao-artefatos.md)
- Depende de: Fase F0 do Plano 1 (porta, cliente e servidor laya)
- Responsável: Mateus de Castro
- Última revisão: 2026-09-30

## 1. Hipótese

A assinatura de layout é um artefato **rígido**: a DAG 2 aceita nove
`tipo_origem` e, para cada um, um conjunto fechado de chaves. Desde a Fase 1 do
[Plano da Assinatura de Layout](contexto-rapido-assinatura-layout.md), as
**chaves** do `mapeamento_canonico` já são enumeradas por código
(`domain/fallback/target_enumeration.py`). Desde a Fase 2, a **coluna** já é
resolvida pelo contrato (`domain/fallback/column_roles.py`). Desde a Fase 3.2, a
**linha** é resolvida por sinônimo quando o match é único
(`domain/fallback/row_anchoring.py`).

O que sobra para a LLM é um punhado de decisões localizadas — *qual linha*, *qual
constante* — embrulhadas em 17,7 mil tokens de instrução, contrato, exemplo de
estrutura e evidência.

> Trocar a geração de texto por decisões discretas do laya, uma por incógnita, e
> montar a assinatura **deterministicamente** a partir das respostas, sobe o
> acerto de ancoragem e elimina a variância de formato — porque a forma deixa de
> ser produzida por um modelo.

A regra do projeto continua valendo: **nenhum nome de campo, período ou rótulo de
domínio entra no código**. Tudo que o laya recebe é derivado do contrato
semântico e do artefato de extração.

Este plano **não depende** do [Plano 1](plano-decisao-laya-selecao-artefatos.md)
para funcionar: a evidência pode chegar da triagem por decisão ou da seleção por
LLM. Depende apenas da Fase F0 daquele plano, que constrói a porta e o cliente.

## 2. Medições da linha de base

### 2.1 O payload atual de uma unidade

`fallback/siderurgia_mineracao/vale/document_id=c5b0b712…/…/unidades/indicadores_monetarios/entrada_llm_fragmento_layout_signature.json`

| # | Papel da mensagem | chars | % |
| --- | --- | --- | --- |
| 0 | system — papel e escopo | 567 | 0,8 |
| 1 | user — `contexto_execucao` | 255 | 0,4 |
| 2 | system — como ler o contrato | 3.073 | 4,3 |
| 3 | user — contrato + alvos + `entradas_esperadas` + `estrutura_tabelas` | 23.997 | 34,0 |
| 4 | system — como ler o exemplo | 1.312 | 1,9 |
| 5 | user — `exemplo_estrutura_mapeamento_unidade` | 3.823 | 5,4 |
| 6 | system — como usar a evidência | 1.623 | 2,3 |
| 7 | user — `artefatos_contexto_llm` (8 tabelas) | 35.462 | 50,2 |
| 8 | system — instrução final | 547 | 0,8 |
| | **Total** | **70.659** (~17,7k tokens) | |

Dentro da mensagem 3: `contrato_semantico_relevante` 5.883,
`entradas_esperadas` 5.640 (16 entradas), `estrutura_tabelas` 3.122,
`alvos_mapeaveis` 876. Em produção a mesma chamada chega a 105 KiB (Itaú,
tentativa 3), com até três retries corretivos.

### 2.2 Quantas decisões existem de fato

As 16 `entradas_esperadas` dessa unidade se decompõem em quatro campos por
indicador. Três deles o código já sabe responder.

| Campo | Qtd. | O que decide | Quem |
| --- | --- | --- | --- |
| `.valor` | 4 | arquivo e linha; a coluna vem da Fase 2.3 | **modelo** |
| `.periodo` | 4 | nada: é o cabeçalho da coluna já resolvida → `cabecalho_de_tabela` | código |
| `.moeda` | 4 | um valor de `dominio: [BRL, USD]` | código |
| `.escala` | 4 | um valor de `dominio: [unidades…bilhoes]`, com `sinonimos` que batem `"US$ milhões"` literalmente | código |

**Quatro decisões reais**, contra 17,7k tokens de contexto.

### 2.3 Evidência que chega à unidade

Os oito artefatos que a execução real carregou para `indicadores_monetarios`
somam **130 linhas**: table001=14, table002=30, table004=14, table005=13,
table006=13, table007=19, table008=4, table013=23.

## 3. Micro-etapas de hoje

Recorte do fluxo depois que a evidência já foi selecionada e podada.

| # | Etapa | Onde | Natureza |
| --- | --- | --- | --- |
| 1 | `enumerate_target_entries` → `entradas_esperadas`, a lista fechada de chaves | `target_enumeration.py:318` | determinística |
| 2 | `analyze_tables` → `estrutura_tabelas`: cabeçalho, coluna de rótulo, segmentos, `papel_por_coluna` | `column_roles.py:135` | determinística |
| 3 | `attach_resolved_row_anchors` → âncora quando o sinônimo casa **uma** linha só | `row_anchoring.py:324` | determinística |
| 4 | `_fragment_payload_for_unit` — monta as 9 mensagens | `mapping_unit_generation.py:305` | determinística |
| 5 | **Chamada LLM #2** — fragmento, até 3 retries corretivos | `fragment_generation.py` | **LLM** |
| 6 | `validate_layout_fragment`: paths no contrato, seletores de array, índices posicionais, `valor_aceito`, âncora de linha, papel de coluna | `candidate_validation.py:175` | determinística |
| 7 | `_merge_layout_fragments` → candidato consolidado | `candidate_composition.py` | determinística |
| 8 | `_persist_unmapped_optional_observations` | `mapping_unit_generation.py:206` | determinística |

**Só a etapa 5 é modelo.** Este plano a substitui por três decisões pequenas mais
uma montagem determinística, e mantém a 6 **sem nenhuma alteração** — é esse o
critério que prova a tese.

## 4. Desenho proposto

### 4.1 Princípio

O laya nunca escreve JSON de layout. Ele responde uma pergunta fechada por
incógnita, e o código monta a assinatura. Três propriedades a preservar:

1. **Forma deixa de ser risco.** O candidato é montado por
   `domain/decision/assembly.py` e validado pelo mesmo
   `FallbackCandidateValidationService`. Violar o validador passa a ser bug de
   código, não variância de modelo.
2. **Abstenção é resposta válida.** Sem confiança, o código registra a ausência
   em vez de adivinhar — a mesma regra de `resolve_row_anchor`. Ver a decisão
   aberta 3, que qualifica isso para campos obrigatórios.
3. **Reprodutibilidade.** Decodificação gulosa e cache por hash da pergunta. A
   lição registrada em `row_anchoring.py` — o mesmo payload devolvendo respostas
   diferentes — não pode se repetir com o laya.

### 4.2 As três decisões

#### B — Ancoragem de linha

A incógnita principal. `resolve_row_anchor` continua sendo a primeira palavra:
onde o sinônimo do contrato casa exatamente uma linha, o código decide e o laya
não é consultado. O laya entra onde ela devolve `None` — zero correspondências,
ou duas ou mais.

É o caso que hoje trava: "Vendas Contratadas Brutas" contra "Vendas Líquidas
100%" casam o mesmo sinônimo e o código desiste. A pergunta é pequena e
bem-posta: entre estas linhas candidatas, qual é o indicador?

- entrada: rótulos de linha, cabeçalhos, e o critério vindo do contrato
- saída: `(arquivo_origem, indice_linha, rotulo_linha)` ou abstenção

#### C — Contexto de domínio fechado

Campos como `moeda` e `escala`, cujas opções são
`entidades.<campo>.dominio` — 2 e 4 elementos. Tenta primeiro o casamento
determinístico por `entidades.<campo>.sinonimos`: no contrato de siderurgia,
`escala.sinonimos` contém `"US$ milhoes"` e o cabeçalho da `table001` da Vale é
exatamente `"US$ milhões"`, então boa parte resolve sem modelo. O laya entra no
resíduo.

- entrada: cabeçalho e rótulos da tabela escolhida
- saída: um elemento do domínio, ou abstenção

#### D — Coluna residual

Só onde `ColumnRoleResolution.ambiguos` ou `ausentes` não está vazio — quando o
contrato deriva um período mas nenhuma coluna o casa sozinha.

- entrada: cabeçalhos lidos pela Fase 2
- saída: índice de coluna, ou abstenção

### 4.3 Formas da pergunta

As mesmas três estratégias do Plano 1, medidas aqui sobre a ancoragem:

| Estratégia | Pergunta | Opções | Chamadas |
| --- | --- | --- | --- |
| `binaria` | "esta linha é este indicador?" | sim / não | `n_linhas × n_alvos` |
| `multiclasse_por_evidencia` | "qual indicador esta linha é?" | alvos + `nenhum` | `n_linhas` |
| `multiclasse_por_alvo` | "qual destas linhas é este indicador?" | linhas + `nenhuma` | `n_alvos` |

A terceira é a que corresponde ao problema: escolher **entre linhas que
competem pelo mesmo alvo** é exatamente o que `resolve_row_anchor` não consegue
fazer.

### 4.4 Orçamento de chamadas, medido

Vale, supondo que a triagem aprove os mesmos 8 artefatos que a execução atual
carregou (130 linhas por unidade):

| Unidade | Indicadores | Linhas | `binaria` | `por_evidencia` | `por_alvo` |
| --- | --- | --- | --- | --- | --- |
| `indicadores_monetarios` | 4 | 130 | 520 | 130 | 4 |
| `indicadores_percentuais` | 1 | 130 | 130 | 130 | 1 |
| `indicadores_razao` | 1 | 130 | 130 | 130 | 1 |
| **Total** | **6** | | **780** | **390** | **6** |

As etapas C e D acrescentam poucas unidades: C é no máximo um par (moeda,
escala) por observação, e só no resíduo do casamento por sinônimo; D só onde o
papel de coluna ficou ambíguo.

O número da coluna `binaria` depende inteiramente de quantos artefatos a triagem
aprovar — é a razão de o [Plano 1](plano-decisao-laya-selecao-artefatos.md) ser
o primeiro a ser implementado, ainda que não seja pré-requisito lógico.

### 4.5 O que o código deriva sem perguntar

`tipo_origem` **não é decisão de modelo**. É função de `(campo da entrada,
modo_array, tipo do artefato)`, tabelada a partir do que a DAG 2 aceita
([resolucao-deterministica-schema-saida-dag2.md](../architecture/resolucao-deterministica-schema-saida-dag2.md)):

| Condição na entrada enumerada | `tipo_origem` | Chaves preenchidas por código |
| --- | --- | --- |
| `modo_array=item`, campo terminal numérico, evidência = tabela | `celula_de_tabela` | `arquivo_origem`, `seletor_linha.{coluna_rotulo,valor_aceito,indice_linha_esperado}`, `seletor_coluna.indice_coluna_esperado` |
| campo de contexto que o contrato liga a um papel de período | `cabecalho_de_tabela` | `arquivo_origem`, `seletor_coluna.indice_coluna_esperado`, `papel_periodo` |
| campo de contexto cujo valor pertence a `entidades.<campo>.dominio` | `valor_fixo` | `valor_fixo` (a etapa C escolhe entre os elementos) |
| `modo_array=colecao` (requisito é o próprio array) | `linhas_de_tabela` | `arquivo_origem`, `segmentos`/`faixas_linhas`, `indices_colunas` |
| evidência = `charts/<g>/normalized_rows.json`, um campo | `campo_json` | `arquivo_origem`, `caminho_json` |
| evidência = dois gráficos com a mesma chave | `juncao_de_registros_json` | `fontes[].{arquivo_origem,caminho_chave,campos}` |
| abstenção em qualquer etapa | — | `campos_nao_mapeados` com `artefatos_verificados` |

## 5. Contratos de dados

A porta é a mesma do [Plano 1](plano-decisao-laya-selecao-artefatos.md#5-contratos-de-dados),
com `tipo` assumindo `ancoragem_linha`, `contexto_dominio` ou `papel_coluna`.

## 6. Agregação e abstenção

`domain/decision/aggregation.py`, puro e testável:

- **Threshold por tipo de pergunta**, fixado na F1 sobre gabarito, nunca ajustado
  no fluxo.
- **Margem mínima**: abaixo de δ entre o primeiro e o segundo score, abstém,
  mesmo havendo argmax.
- **Conflito**: duas entradas do mesmo requisito apontando para a mesma célula
  `(arquivo, linha, coluna)` é conflito registrado e abstenção das duas — o
  contrato exige observações distintas.
- **Consenso com o código**: onde `resolve_row_anchor` já resolve por sinônimo
  único, o código vence e a divergência é registrada como
  `decisao_divergencia_do_deterministico`. Mantém a hierarquia atual e cria um
  sinal contínuo de qualidade do laya sem precisar de gabarito.

## 7. Fases

Guardas de todas as fases: `e2e_apto_para_bronze`,
`resolucao_cobertura_obrigatorios`, `revalidacao_gate_efetivo`,
`validacao_cobertura_de_regras`, `assinatura_f0_selecao_revocacao`.

### F0 — Dependência

A porta, o cliente `laya_client.py`, o `fake_client.py`, as variáveis de ambiente
e o serviço Docker vêm da
[Fase F0 do Plano 1](plano-decisao-laya-selecao-artefatos.md#f0--porta-cliente-e-servidor-local).
Este plano não a reimplementa.

### F1 — Harness offline da ancoragem

**Release** `exp-laya-f1-ancoragem-harness` · **Alvo**: a primeira comparação
entre as três estratégias sobre os 18 gabaritos, sem tocar no fluxo.

`eval/gabaritos/<document_id>.json` já traz, por observação, `arquivo_origem`,
`indice_linha`, `rotulo_linha`, `indice_coluna` e `cabecalho_coluna` — o rótulo
exato de que as etapas B, C e D precisam.

Criar:
- `domain/decision/row_decision.py` — monta a pergunta B a partir de
  `entradas_esperadas`, `estrutura_tabelas` e dos artefatos carregados. Puro.
- `scripts/avaliar_decisao_ancoragem.py` — reconstrói as perguntas B/C/D de cada
  gabarito, roda as três estratégias e pontua.
- métricas em `domain/observability/decision_evaluation.py`.

| Métrica | Dir. | O que mede |
| --- | --- | --- |
| `decisao_ancoragem_linha_correta` | ↑ | etapa B contra `ancoragens[].indice_linha`/`rotulo_linha` |
| `decisao_ancoragem_arquivo_correto` | ↑ | etapa B contra `ancoragens[].arquivo_origem` |
| `decisao_contexto_dominio_correto` | ↑ | etapa C contra os campos de contexto do gabarito |
| `decisao_coluna_residual_correta` | ↑ | etapa D contra `indice_coluna` |
| `decisao_abstencoes` | ↓ | incógnitas sem decisão |
| `decisao_conflitos` | ↓ | pares de entradas na mesma célula |
| `decisao_divergencia_do_deterministico` | ↓ | laya ≠ `resolve_row_anchor` onde o código resolveu |
| `decisao_chamadas_total` / `decisao_latencia_p95_ms` | ↓ | custo por documento |

**Portão**: só passa para F2 se a melhor estratégia empatar ou superar a LLM em
`assinatura_f3_rotulo_linha_correto` da release base.

### F2 — Ancoragem de linha por decisão

**Release** `exp-laya-f2-ancoragem` · **Alvo**: subir
`assinatura_f3_rotulo_linha_correto`. Guarda extra:
`assinatura_f3_ausencia_falso_positivo`.

`resolve_row_anchor` continua sem mudança de assinatura. Onde devolve `None`, o
novo `row_decision.py` monta a pergunta B. `attach_resolved_row_anchors`
(`mapping_unit_generation.py:305`) ganha a variante que consulta a porta.

Persistir `decisao_ancoragem.json` por unidade.

**Aceite**: teste com duas linhas casando o mesmo sinônimo mostrando que hoje
abstém e passa a decidir; teste de que abstenção continua registrando ausência,
não um chute.

### F3 — Contexto de domínio fechado e coluna residual

**Release** `exp-laya-f3-contexto` · **Alvo**: subir
`assinatura_f1_contexto_irmao_presente` e `assinatura_f2_papel_coluna_correto`.

**Aceite**: teste mostrando que `moeda`/`escala` resolvidos por sinônimo não
chamam o laya; teste de que um valor fora do domínio é recusado antes da
montagem.

### F4 — Montagem determinística da assinatura

**Release** `exp-laya-f4-montagem` · **Alvo**: `avaliacao_candidato_valido` = 1,0
e `llm_tokens_total` da etapa `layout_signature_candidato` → 0.

Criar:
- `domain/decision/assembly.py` — decisões para `mapeamento_canonico` +
  `campos_nao_mapeados` + `fontes_relevantes`, pela tabela de 4.5. Puro, sem I/O,
  sem nome de domínio.
- `use_cases/fallback/decision_layout_generation.py` — orquestra B→C→D→montagem
  por unidade, substituindo `_generate_layout_fragment` quando
  `ATLAS_ASSINATURA_MOTOR=decisao`.

Fechar a decisão aberta 1 com `tests/unit/domain/test_decision_assembly.py`
parametrizado pelos quatro contratos reais em `infra/minio-bootstrap/contracts/`.

**Aceite**: o candidato montado passa no `FallbackCandidateValidationService`
**sem nenhuma alteração no validador**. A DAG 3 completa
`criacao_inicial_layout` sem chamada de LLM, e os blocos `comum-contrato`,
`candidato-estrutura`, `candidato-artefatos`, `candidato-final` e
`candidato-escopo-criacao-inicial` (`prompt_sets.py:93`) param de ser resolvidos
nesse escopo — mantidos no repositório, porque correção parcial e regeneração
total continuam na LLM.

### F5 — Regras de detecção geradas da decisão

**Release** `exp-laya-f5-regras` · **Alvo**: **`validacao_cobertura_de_regras` > 0
e `revalidacao_gate_efetivo` > 0**.

O backfill mostrou que **todos** os layouts ativos de construtoras foram
publicados com `regras_deteccao_mudanca` vazio — logo a validação da DAG 2 sempre
retorna `compativel` e o gate aprova sem evidência, com
`revalidacao_gate_efetivo` medindo 0,000 nas 39 publicações
([observabilidade-e-metricas-langfuse.md](../architecture/observabilidade-e-metricas-langfuse.md)).
Quando a ancoragem passa a ser decisão explícita, o código sabe o bastante para
emitir as regras:

| Decisão tomada | Regra derivável |
| --- | --- |
| artefato usado | `arquivo_existe` |
| linha ancorada por rótulo | `linha_existe_em_tabela` com `indice_linha_esperado` |
| coluna resolvida por papel | `perfil_colunas_periodo_existe_em_tabela` |
| célula lida e normalizada | `valor_normalizavel` |

Criar `domain/decision/detection_rules.py`.

**Aceite**: layout publicado pela DAG 3 traz `regras_deteccao_mudanca` não vazio;
a revalidação executa ao menos uma regra; `revalidacao_gate_efetivo` deixa de ser
0,000.

### F6 — Mapped tasks e virada do default

**Release** `exp-laya-f6-mapped` · **Alvo**: nenhuma métrica de qualidade se move;
`e2e_duracao_segundos` não piora.

```text
montar_plano_mapeamento
  -> (triagem, do Plano 1)
  -> decidir_ancoragens_unidade.expand(evidencias)
  -> montar_assinatura_por_unidade.expand(decisoes)
  -> consolidar_layout_por_unidades
  -> persistir -> revalidar DAG 2 -> publicar
```

Requisitos de [plano-dag3-prompts-mapped-tasks.md](plano-dag3-prompts-mapped-tasks.md):
não passar `loaded_context` inteiro por XCom; identidade persistida sempre por
`unit_id`, nunca `map_index`; retries do Airflow separados dos internos.

Só ao fim desta fase `ATLAS_ASSINATURA_MOTOR` vira `decisao` por default, e
apenas para `criacao_inicial_layout`.

## 8. Observabilidade

- **MinIO** guarda toda pergunta e resposta: `decisao_ancoragem.json`,
  `decisao_contexto.json`, `decisao_papel_coluna.json`, e
  `decisoes_agregadas.json` com o que a montagem usou.
- **Langfuse** recebe um span por etapa por unidade
  (`fallback.decisao.ancoragem`, `fallback.decisao.contexto`) com os agregados,
  não uma generation por chamada: 780 generations tornariam o trace ilegível.
- O trace carrega `laya_modelo` e `laya_versao` no metadata, ao lado de `commit`
  e `branch`.
- Novo dataset off-line `atlas-decisao-ancoragem`, populado dos 18 gabaritos com
  os itens negativos das ausências (`assinatura_f3_ausencia_*`), para medir falso
  positivo.

## 9. Testes

| Arquivo | Cobre |
| --- | --- |
| `tests/unit/domain/test_decision_row_anchoring.py` | pergunta B só com termos do contrato; código vence o modelo onde resolve |
| `tests/unit/domain/test_decision_assembly.py` | tabela de 4.5 nos quatro contratos reais; candidato passa no validador atual |
| `tests/unit/domain/test_decision_detection_rules.py` | regras derivadas das âncoras |
| `tests/unit/application/test_decision_layout_generation.py` | orquestração com `fake_client`, sem rede |
| regressões de fallback existentes | com `ATLAS_ASSINATURA_MOTOR=llm`, nada muda |

CI: `ruff check src tests/unit scripts/validate_repository_structure.py` e
`pytest tests/unit`.

## 10. Riscos e decisões abertas

| Risco | Mitigação |
| --- | --- |
| Latência: até 780 chamadas por documento na binária | lote, cache por `question_id`, e a triagem do Plano 1 limitando quantas linhas chegam aqui |
| Calibração do zero-shot | threshold e margem fixados na F1, sobre gabarito, em constantes testadas |
| Vazamento de domínio no critério | só pode ser montado de `contrato_semantico`; teste específico proíbe literal no código |
| Modelo não determinístico entre execuções | decodificação gulosa e cache; `decisao_divergencia_do_deterministico` denuncia deriva |
| Repetir o erro de 2026-09-18 (ajuste só de prompt) | a decisão é fechada — opções enumeradas por código — e a forma sai da montagem. É a lição "código enumerando o determinístico" aplicada |

**Decisões abertas:**

1. **Critério que separa contexto-cabeçalho de contexto-constante.** Proposta: é
   constante quando `entidades.<campo>.dominio` existe; é cabeçalho quando o
   campo é a chave declarada em `chaves_de_item` para o array interno, ou quando
   `requisitos_mapeamento.papeis` deriva um período para o seletor daquele array.
   Nos quatro contratos inspecionados a regra separa `periodo` de
   `moeda`/`escala` corretamente. Se estiver errada, o efeito é o pior tipo: um
   `.periodo` virando `valor_fixo` congela o rótulo do trimestre na assinatura e
   resolve **certo neste documento e silenciosamente errado no próximo**, sem
   falhar validação. Fechar com teste na F4.

2. **Limite de entrada do laya.** A `por_alvo` precisa caber 130 rótulos de linha
   como opções (~5k chars). Se não couber, a pergunta é particionada em janelas —
   e aí os scores de janelas diferentes não são comparáveis, porque a
   distribuição normaliza dentro das opções presentes: o 0,90 de uma janela ruim
   não é melhor que o 0,70 de uma janela boa. Exige uma segunda passada de
   desempate entre os vencedores de cada janela. Um score absoluto calibrado, em
   vez de distribuição, dispensaria isso. Saber antes da F1 evita produzir
   números não comparáveis.

3. **Abstenção em campo obrigatório.** Hoje, declarar ausência num campo
   obrigatório levanta `UnmappedRequiredFieldsError`
   (`candidate_validation.py:639`) e a DAG 3 falha **sem retry**
   (`candidate_generation.py:184`) — a execução termina sem candidato nenhum. A
   linha de base já mostra que 44% das execuções não chegam a produzir candidato,
   então abstenção agressiva empurra esse número para cima. Recomendação: campo
   **opcional** → ausência declarada; campo **obrigatório** → escalar aquela
   entrada específica para a LLM, com payload mínimo (uma entrada, um artefato),
   em vez de matar a execução. Isso torna `ATLAS_DECISAO_ESCALAR_ABSTENCAO`
   ligada por default para obrigatórios.

4. **Gráficos na etapa B.** `charts/<g>/normalized_rows.json` não tem coluna de
   rótulo como tabela; a identidade de um registro está na série ou na categoria
   (`attributes.periodo`, `measures.valor`). A pergunta equivalente precisa ser
   definida. A F1 mede tabelas e gráficos separadamente antes de a F2 tratar os
   dois.

## 11. Fora de escopo

- A seleção de artefatos — é o
  [Plano 1](plano-decisao-laya-selecao-artefatos.md).
- `correcao_parcial_mapeamento` e `regeneracao_total_mapeamento`: continuam na
  LLM; o motor é escolhido por escopo.
- `blocks/`, `text_candidates/`, `text_structures/`.
- Treinar ou ajustar o laya: zero-shot por instrução, e os gabaritos são conjunto
  de avaliação. Se a F1 reprovar, a discussão de fine-tune volta com número na
  mão.
- Mudar o `FallbackCandidateValidationService`, o contrato semântico, o
  resolvedor da DAG 2 ou os gates de publicação.

## 12. Referências

- [Plano 1 — Seleção de Artefatos](plano-decisao-laya-selecao-artefatos.md)
- [contexto-rapido-assinatura-layout.md](contexto-rapido-assinatura-layout.md)
- [plano-dag3-prompts-mapped-tasks.md](plano-dag3-prompts-mapped-tasks.md)
- [fallback-llm-e-geracao-layout-dag3.md](../architecture/fallback-llm-e-geracao-layout-dag3.md)
- [resolucao-deterministica-schema-saida-dag2.md](../architecture/resolucao-deterministica-schema-saida-dag2.md)
- [observabilidade-e-metricas-langfuse.md](../architecture/observabilidade-e-metricas-langfuse.md)
- [desenvolvimento-orientado-a-metricas.md](../guides/desenvolvimento-orientado-a-metricas.md)
- [ADR 0004](../adr/0004-resolucao-deterministica-com-fallback-llm.md), [ADR 0009](../adr/0009-observabilidade-por-projecao-de-artefatos.md), [ADR 0011](../adr/0011-resolucao-dirigida-pelo-contrato-e-legado-por-ausencia.md)
