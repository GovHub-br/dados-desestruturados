# Plano: perfis reutilizáveis para assinaturas de layout

## Status

Proposto.

## Objetivo

Fazer com que uma assinatura de layout descreva uma **família estrutural de documentos**, e não uma ocorrência específica de um PDF. Assim, a mesma assinatura poderá continuar resolvendo documentos mensais ou trimestrais quando mudarem página, identificador de tabela, quantidade de linhas, competência ou posição física de um bloco, desde que o significado e a estrutura observável permaneçam compatíveis.

O resultado desejado é reduzir drasticamente a criação de assinaturas novas. Uma assinatura nova deverá ser necessária somente quando houver uma mudança estrutural ou semântica real, não por detalhes acidentais da extração.

O plano preserva três princípios já adotados no projeto:

- a DAG 2 continua sendo a autoridade determinística para produzir os dados;
- a LLM pode propor ou classificar regras, mas não inventa valores finais;
- um mapeamento ambíguo deve falhar com evidência, e não selecionar uma fonte plausível silenciosamente.

## Problema atual e diagnóstico

Hoje a assinatura materializada guarda referências físicas, por exemplo:

```json
{
  "tipo_origem": "linhas_de_tabela",
  "arquivo_origem": "tables/table005.json",
  "linha_inicial": 12,
  "linha_final": 22,
  "campos": {
    "instituicao_financeira": {"indice_coluna": 0},
    "unidades_mensais": {"indice_coluna": 3}
  }
}
```

Esse formato é adequado para a resolução de uma execução: é auditável e aponta exatamente para a evidência usada. Porém, não representa bem uma família de layouts. Se o Docling numerar a tabela como `table006`, se uma instituição adicional alterar os limites de linhas ou se a tabela mudar de página, a regra física deixa de funcionar mesmo quando o PDF mantém o mesmo significado.

O caso ABECIP tornou esse limite explícito. O script `scripts/gerar_assinaturas_layout_abecip_historico.py` reúne regras úteis, mas contém condicionais por competência e limites físicos por documento. Foi uma forma segura de estabilizar dados históricos rapidamente; não deve se tornar o padrão para novas famílias documentais.

Há hoje dois conceitos condensados em uma única assinatura:

1. **Regra reutilizável:** “a série mensal está na tabela cuja estrutura contém estes títulos, cabeçalhos e papéis de coluna”.
2. **Vinculação da execução:** “neste PDF essa tabela foi `table005.json`, as linhas observadas foram 12–22 e a coluna `No mês` ficou no índice 3”.

Separá-los mantém a evidência precisa sem transformar cada execução em nova regra de layout.

| Componente atual | Responsabilidade | Limite para reutilização |
| --- | --- | --- |
| `mapping_plan.py` | Divide requisitos por raiz semântica | Uma unidade pode conter estruturas físicas heterogêneas. |
| `fragment_generation.py` | Faz uma chamada LLM por unidade | Solicita caminhos da execução, não uma regra reutilizável. |
| `unit_mapping_prompts.py` e `candidate_prompts.py` | Explicam tarefa e JSON | Não distinguem perfil estrutural de instância. |
| `candidate_validation.py` | Valida candidato | Valida principalmente assinatura física. |
| `source_mapping_resolvers.py` | Resolve tabelas, blocos e células | Trabalha com arquivos, linhas e colunas fixados. |
| `resolve_schema.py` | Aplica layout + contrato | Não possui descoberta de perfil e vinculação. |

## Conceitos propostos

### Perfil de layout

`layout_profile` é uma regra declarativa, versionada e reutilizável para uma família estrutural de PDFs. Usa fontes lógicas, âncoras estruturais, papéis de colunas e limites semânticos; não usa `document_id`, página, caminho `tableNNN.json` ou números de linha específicos como única forma de seleção.

```text
profile_id: abecip-financiamentos-sbpe-tabelas-separadas
profile_version: 1.0.0
```

### Vinculação de perfil

`profile_binding` é o artefato determinístico de uma execução. Registra qual perfil foi aplicado, quais âncoras foram encontradas, quais fontes físicas foram escolhidas, as variáveis derivadas e os intervalos finais de linhas e colunas. É a prova de como o perfil virou uma assinatura aplicável ao PDF concreto.

### Assinatura materializada

É a assinatura no formato já aceito pela DAG 2. Ela é gerada deterministicamente por `layout_profile + profile_binding` e continua referenciando arquivos físicos exatos. Isso mantém compatibilidade com o resolvedor atual e layouts legados.

### Fonte lógica

Nome estável para uma evidência de negócio, como `financiamentos_mensais`, `poupanca_saldos`, `serie_historica` ou `instituicoes_por_modalidade`. A fonte lógica é localizada no inventário da execução por âncoras, não por nome de arquivo fixo.

## Novo padrão de perfil

O formato abaixo é ilustrativo. A especificação JSON Schema deve ser criada antes do resolvedor.

```json
{
  "tipo_artefato": "layout_profile",
  "profile_id": "abecip-financiamentos-sbpe-tabelas-separadas",
  "versao_perfil": "1.0.0",
  "status": "aprovado",
  "dominio": "abecip",
  "entidade_slug": "abecip",
  "tipos_documento": ["boletim-mensal-financiamento"],
  "contratos_compativeis": ["abecip@>=2.3.0,<3.0.0"],
  "variaveis_documento": {
    "competencia_referencia": {"origem": "manifest.periodo"},
    "ano_referencia": {"derivacao": "year(competencia_referencia)"},
    "ano_anterior": {"derivacao": "ano_referencia - 1"}
  },
  "fontes_logicas": {
    "financiamentos_mensais": {
      "tipo": "tabela",
      "candidatos": [{
        "titulo": {"contem_todos": ["financiamentos", "sbpe"]},
        "cabecalhos": {"contem_todos": ["unidades", "valores", "no mes"]},
        "minimo_linhas": 2,
        "minimo_colunas": 4
      }],
      "unicidade_obrigatoria": true
    }
  },
  "segmentos_logicos": {
    "instituicoes": {
      "fonte": "financiamentos_mensais",
      "inicio": {"linha": {"igual_normalizado": "instituicao financeira"}},
      "fim": {"antes_da_proxima_linha": {"igual_normalizado": "total"}}
    }
  },
  "papeis_de_coluna": {
    "instituicoes": {
      "instituicao_financeira": {"cabecalho": {"contem_todos": ["instituicao"]}},
      "unidades_mensais": {"cabecalho": {"contem_todos": ["unidades", "no mes"]}},
      "volume_mensal_milhoes": {"cabecalho": {"contem_todos": ["valores", "no mes"]}}
    }
  },
  "mapeamentos": {
    "financiamentos_imobiliarios.por_modalidade_e_instituicao": {
      "origem_logica": "financiamentos_mensais",
      "segmento": "instituicoes",
      "tipo_origem_materializado": "linhas_de_tabela"
    }
  }
}
```

O exemplo não determina que todos os documentos tenham título de tabela ou uma linha chamada `Total`. Cada perfil declara apenas âncoras observáveis de sua família. Outros perfis poderão localizar seções, blocos textuais ou gráficos, desde que exista gramática determinística equivalente.

### Gramática segura de seletores

O executor deve aceitar uma gramática pequena e validada:

- comparação de texto normalizado (`igual_normalizado`, `contem_todos`);
- tokens obrigatórios e opcionais em títulos e cabeçalhos;
- intervalo delimitado por âncora inicial e final;
- primeira, última ou próxima ocorrência **única** de âncora;
- seleção de coluna por papel semântico de cabeçalho, com índice esperado apenas como verificação adicional;
- mínimos/máximos estruturais de linhas e colunas;
- alternativas declaradas de fonte ou segmento, em ordem explícita.

Normalização remove apenas diferenças previsíveis de OCR e formatação — caixa, acentos, espaços repetidos e pontuação semanticamente irrelevante. Não deve se tornar busca livre por regex nem inferir coluna por semelhança vaga.

Toda seleção produz `evidencia_de_match`: título, cabeçalhos, critérios satisfeitos, linhas/colunas escolhidas e razão do desempate. Sem resultado único, a DAG 2 interrompe com erro auditável.

### Exemplo de binding por execução

```json
{
  "tipo_artefato": "profile_binding_layout",
  "profile_id": "abecip-financiamentos-sbpe-tabelas-separadas",
  "versao_perfil": "1.0.0",
  "document_id": "...",
  "execution_id": "...",
  "variaveis": {"competencia_referencia": "2026-05", "ano_referencia": 2026},
  "fontes": {
    "financiamentos_mensais": {
      "arquivo_origem": "tables/table003.json",
      "evidencia_de_match": {"titulo": "...", "cabecalhos": ["..."]}
    }
  },
  "segmentos": {"instituicoes": {"linha_inicial": 12, "linha_final": 22}},
  "colunas": {"instituicoes": {"instituicao_financeira": 0, "unidades_mensais": 3}}
}
```

O materializador transforma esse objeto no formato atual de `layout_signature_deterministico.json`; os resolvers existentes continuam recebendo `arquivo_origem`, `linha_inicial`, `linha_final` e `indice_coluna`.

## Mudanças que devem ou não criar perfil novo

| Alteração no novo PDF | Reutiliza perfil? | Como |
| --- | --- | --- |
| `table003.json` passa a `table005.json` | Sim | Âncoras vinculam o arquivo novo. |
| Tabela muda de página | Sim | Página não é identidade primária. |
| Entram/saem instituições ou meses | Sim | Segmentos terminam por âncora, não por linha estática. |
| Mesma coluna muda de posição | Sim, se cabeçalho é único | Papel de coluna é resolvido pelo cabeçalho. |
| Docling gera tabela composta em vez de duas | Talvez | Estratégia alternativa declarada; senão, perfil novo. |
| Indicador passa de tabela para parágrafo/gráfico | Não inicialmente | Novo perfil e validação para fonte nova. |
| Campo muda significado, unidade ou granularidade | Não | Evolução do contrato e perfil compatível. |

O objetivo não é uma assinatura universal permissiva. É um catálogo pequeno de perfis com fronteiras claras e verificáveis.

## Fluxo proposto

```text
DAG 1: extração Docling
        |
        v
Inventário estrutural determinístico
        |
        +--> catálogo de perfis -> match único?
                                  |
                   sim ----------+--> profile_binding
                                  |          |
                                  |          v
                                  |    assinatura materializada
                                  |          |
                                  +------> DAG 2 resolve e valida
                                  |
                   não / ambíguo -+--> DAG 3 assistida por LLM
                                              |
                                              v
                                    propõe perfil/estratégia, nunca valores
                                              |
                                              v
                                    replay determinístico e publicação segura
```

### 1. Inventário estrutural determinístico

Antes de qualquer LLM, gerar projeção compacta de cada artefato de tabela:

- caminho físico, `table_id`, página e seção quando disponíveis;
- título e cabeçalhos normalizados;
- quantidades de linhas e colunas;
- ocorrências relevantes da primeira coluna;
- tipos de células observados;
- `bbox` e metadados para auditoria.

O inventário serve ao matcher e à seleção de fontes da DAG 3; não exige enviar todas as tabelas completas.

### 2. Match de perfil

Para cada perfil compatível com domínio, entidade, tipo de documento e contrato:

1. avaliar candidatas de cada fonte lógica;
2. verificar critérios obrigatórios;
3. calcular escore explicável somente entre candidatas válidas;
4. exigir unicidade das fontes obrigatórias;
5. derivar segmentos, colunas e variáveis;
6. materializar assinatura e executar validação já existente da DAG 2.

Não haverá “melhor candidato” quando duas fontes passarem sem desempate declarado. Isso é ambiguidade, não sucesso.

### 3. Ordem de resolução da DAG 2

1. `layout_signature_object_key` explícito no trigger;
2. perfil explicitamente solicitado por `layout_profile_id`;
3. catálogo de perfis ativos compatíveis;
4. assinatura legada atual (`current.json`) durante migração;
5. encaminhamento controlado à DAG 3.

Em resolução por perfil, persistir `inventario_estrutural.json`, `profile_match_result.json`, `profile_binding.json`, `layout_signature_materializada.json` e a auditoria já existente.

### 4. Papel revisado da DAG 3 e da LLM

A LLM deixa de criar assinatura física por documento sempre que possível. Seus usos, em ordem de custo, serão:

1. **classificação de compatibilidade:** escolher entre perfis candidatos explicitamente apresentados quando o matcher não puder desempatar;
2. **proposta de estratégia alternativa:** descrever outra forma declarativa de localizar fonte conhecida;
3. **criação de perfil candidato:** somente quando não existir perfil compatível.

A geração continua por unidades semânticas, mas devolve regras reutilizáveis: fontes lógicas, âncoras, papéis de coluna, limites semânticos e alternativas. A consolidação gera `layout_profile` candidato e binding de teste para o PDF de origem.

## Mudanças nos prompts

Os prompts robustos atuais de geração de fragmento devem ser preservados: explicam contrato, fontes permitidas, estrutura de resposta, exemplos e restrições de JSON. A mudança é de tarefa e exemplo de saída, não remoção de instruções importantes.

### Instruções a adicionar

- “Você está definindo uma regra reutilizável para documentos da mesma família.”
- “Não use `table001.json`, página, `document_id`, competência ou intervalo fixo de linha como única forma de localizar fonte.”
- “Defina fonte lógica por título, cabeçalhos, seção e/ou âncoras verificáveis deterministicamente.”
- “Use intervalo entre âncoras para coleções com tamanho variável.”
- “Declare papel de cada coluna pelo cabeçalho; índice observado é apenas evidência ou guarda de consistência.”
- “Se não houver âncora estrutural suficiente, devolva lacuna explícita; não invente regra generalizável.”
- “Não devolva valores extraídos, cabeçalhos operacionais, versão de publicação ou referências físicas finais.”

### Exemplo e reparo

Substituir exemplo de fragmento físico por exemplo completo, curto e válido de `profile_fragment`: fonte lógica, critérios obrigatórios/opcionais, segmento delimitado, papéis de coluna, mapeamentos do subesquema e lacuna explícita. Prompts de reparo devem apresentar erros determinísticos em termos de perfil, por exemplo: “âncora de fim ocorre em duas fontes; restrinja por cabeçalhos”.

### Contexto, tokens e reasoning

O inventário estrutural e subconjunto de artefatos continuam limitando contexto. Após perfil aprovado, a resolução deve ser totalmente determinística e não chamar LLM. Na criação de perfil, enviar somente subesquema, inventário, janelas das candidatas, perfis compatíveis e exemplos do novo formato — nunca toda extração ou candidatos completos de outros documentos.

## Alterações de código planejadas

| Área | Mudança |
| --- | --- |
| `domain/layout_profiles/` (novo) | Modelos imutáveis de perfil, binding, evidência e gramática; normalização e match puros. |
| `application/use_cases/resolution/` | Caso de uso para inventariar, localizar perfil, criar binding e materializar assinatura legada. |
| `source_mapping_resolvers.py` | Continuar consumindo assinatura materializada; apenas extrair helpers puros quando necessário. Não misturar descoberta de perfil com leitura de valores. |
| `resolve_schema.py` | Inserir tentativa de perfil antes do fallback, preservando override explícito e layouts legados. |
| Repositório MinIO de layouts | Ler/escrever catálogo de perfis, versões, hashes e bindings. |
| `mapping_plan.py` | Evoluir unidades de raiz de path para unidades que também respeitem coleção/fonte estrutural, sem quebrar contratos existentes. |
| `fragment_generation.py` | Gerar `profile_fragment` com inventário estrutural, mantendo chamadas por unidade. |
| `unit_mapping_prompts.py`, `candidate_prompts.py`, `payload_assembly.py` | Preservar sequência explicativa e alterar contrato de saída/exemplos para perfis. |
| `candidate_validation.py` | Validar schema do perfil, gramática permitida, ausência de referência física proibida e cobertura do contrato. |
| Ciclo de vida do candidato | Publicar perfil como candidato, executar replay e promover somente após validação. |
| DAGs | Manter DAGs finas: montar dependências, chamar casos de uso e registrar auditoria. |

### Regras de compatibilidade

- O atual `layout_signature_deterministico.json` não será removido nesta iniciativa.
- Layout manual e legado continuam executáveis por chave explícita.
- Perfil só pode ser selecionado se declarar compatibilidade com versão/hash do contrato.
- Perfil aprovado é imutável; mudanças geram versão semântica nova.
- Binding é sempre específico da execução, nunca promovido automaticamente a perfil.
- Perfil candidato não vira padrão global por ter resolvido um PDF.

## Persistência e versionamento no MinIO

```text
layout-profiles/<dominio>/<entidade>/<profile_id>/v1.0.0/profile.json
layout-profiles/<dominio>/<entidade>/<profile_id>/v1.0.0/metadata.json
layout-profiles/<dominio>/<entidade>/<profile_id>/current.json

execucoes/<dominio>/resolucao/.../layout_profile/
  inventario_estrutural.json
  profile_match_result.json
  profile_binding.json
  layout_signature_materializada.json
```

Layouts materializados podem continuar no prefixo atual por compatibilidade, incluindo `referencia_layout_profile` e `referencia_profile_binding`. O ponteiro atual de layouts só deve ser alterado após validação em shadow mode.

## Fases de implementação

### Fase 0 — Baseline e inventário

1. Criar inventário estrutural, sem alterar resolução.
2. Rodar sobre PDFs ABECIP já resolvidos.
3. Agrupar assinaturas por características estruturais, não por competência.
4. Distinguir diferenças de caminho/página/linha de estratégias realmente distintas.

**Saída:** matriz de perfis candidatos e golden files.

### Fase 1 — Modelo e materializador sem ativação

1. Definir JSON Schema e modelos de `layout_profile` e binding.
2. Implementar matcher, derivações e materializador.
3. Converter manualmente layouts ABECIP em poucos perfis iniciais.
4. Comparar assinatura materializada e dados resolvidos com referências aprovadas.

**Aceite:** nenhum valor semântico muda nos golden files.

### Fase 2 — Shadow mode na DAG 2

1. Adicionar `LAYOUT_PROFILE_MODE=disabled|shadow|enforce`.
2. Em `shadow`, gerar match/binding/materialização, persistir auditoria e continuar com layout atual.
3. Medir matches únicos, ambiguidades, não-matches e divergências de saída.

**Aceite:** zero falso match nos documentos conhecidos; divergências explicadas antes de ativar `enforce`.

### Fase 3 — Perfil primeiro com rollback

1. Habilitar `enforce` apenas para ABECIP e perfil aprovado.
2. Manter layout legado como rollback por feature flag ou chave explícita.
3. Encaminhar somente não-match/ambiguidade para DAG 3.

**Aceite:** a maioria dos boletins recorrentes não chama LLM e produz binding completo.

### Fase 4 — Evoluir DAG 3

1. Classificar perfil compatível antes de geração.
2. Migrar fragmentos para `profile_fragment`.
3. Validar generalização e replay em mais de um PDF antes de promoção automática.
4. Permitir aprovação humana quando a família ainda tiver apenas um exemplo.

### Fase 5 — Generalizar por domínio

1. Aplicar padrão às construtoras com perfis próprios, sem copiar âncoras ABECIP.
2. Criar biblioteca de testes compartilhada para tabelas, blocos e gráficos.
3. Incorporar criação/evolução de perfil à skill de contrato/layout.

## Estratégia inicial para ABECIP

Não presumir um único perfil para todos os meses. A extração já mostrou tabelas separadas em alguns documentos e tabelas compostas em outros. A primeira migração deve buscar o menor conjunto honesto, por exemplo:

- perfil para séries em tabelas separadas;
- perfil para tabelas compostas com segmentos internos explícitos;
- perfil histórico que distribui instituições em mais de uma tabela, se âncoras não permitirem tratá-las como fonte lógica única.

Alternativas podem coexistir em um perfil somente quando produzem a mesma semântica e são selecionadas deterministicamente. Se a explicação ficar condicional demais, devem ser perfis diferentes. A métrica é regra pequena e confiável, não menor número de arquivos.

## Validação e testes

### Testes unitários

- normalização de títulos, cabeçalhos e células;
- match único, nenhum match e match ambíguo;
- derivação de competência;
- limites por âncora para listas variáveis;
- papéis de coluna e rejeição de cabeçalhos duplicados;
- materialização dos tipos de origem suportados;
- validação de schema e rejeição de seletor fora da gramática.

### Golden tests e replay

- Reexecutar PDFs ABECIP conhecidos e comparar dados normalizados do `schema_saida_resolvido` com a referência.
- Comparar cobertura, campos não mapeados, fontes e evidências.
- Tratar revisões históricas ABECIP como dado de origem por *vintage*, não como mudança de perfil.

### Testes de perturbação

Verificar que o perfil sobrevive a troca de `tableNNN.json`, página diferente, linhas extras, artefatos reordenados e tabela irrelevante com título parecido. Verificar também falha segura para duas tabelas compatíveis, mudança de unidade/granularidade, cabeçalho crítico ausente ou fonte de tipo incompatível.

### Métricas operacionais

- taxa de match único;
- taxa de ambiguidade e nenhum match;
- PDFs resolvidos por versão de perfil;
- reutilização antes de perfil novo;
- divergência contra replay;
- chamadas LLM, tokens, custo e duração evitados;
- falso match confirmado por auditoria humana.

Ausência de falso positivo é a métrica principal. Ambiguidade encaminhada ao fallback é melhor que uma tabela errada publicada.

## Riscos e mitigação

| Risco | Mitigação |
| --- | --- |
| Perfil flexível escolhe tabela errada | Critérios obrigatórios, unicidade, evidência e falha segura. |
| Perfil rígido exige versões mensais | Âncoras e segmentos semânticos; testes de perturbação. |
| LLM inventa generalização | Gramática fechada, binding de teste e replay em corpus. |
| Migração altera dados aprovados | Shadow mode, golden tests e rollback legado. |
| Contrato se mistura com mudança visual | Compatibilidade explícita por versão/hash. |
| Complexidade excessiva | Materializar no formato legado inicialmente; não reescrever resolvedor inteiro. |

## Critérios para criar ou evoluir perfil

Criar versão nova quando mudarem regras de seleção, segmentação, colunas ou transformação estrutural. Criar perfil novo quando a família tiver fonte/tipo estrutural diferente. Não criar perfil novo por:

- novo mês, trimestre ou ano;
- `document_id` ou `execution_id` novo;
- página ou caminho `tableNNN.json`;
- quantidade de linhas abrangida por âncoras;
- revisão estatística de valores históricos na fonte.

## Definição de pronto

1. Um perfil ABECIP aprovado resolve mais de um PDF com caminhos físicos diferentes.
2. Golden files permanecem semanticamente idênticos às referências.
3. Match ambíguo/incompleto não publica dados.
4. DAG 2 mantém compatibilidade com layout manual e legado.
5. Inventário, match, binding e assinatura materializada ficam persistidos na auditoria.
6. DAG 3 só é chamada se o catálogo não resolver de forma verificável.
7. Perfil novo passa por replay em mais de uma execução ou fica aguardando aprovação humana.

## Ordem recomendada

1. Inventário estrutural e auditoria.
2. Modelos/JSON Schema, matcher e materializador puros com testes.
3. Migração manual de dois ou três perfis ABECIP e golden replay.
4. Shadow mode na DAG 2.
5. Ativação controlada de perfil primeiro.
6. Atualização dos prompts e validadores da DAG 3.
7. Promoção segura e expansão para outros domínios.

Essa ordem prioriza mudança pequena e verificável no caminho crítico. A LLM só passa a gerar a nova abstração depois que executor, gramática e testes já souberem dizer exatamente o que é perfil válido.

## Referências internas

- `scripts/gerar_assinaturas_layout_abecip_historico.py`
- `src/document_processing/application/use_cases/resolution/source_mapping_resolvers.py`
- `src/document_processing/application/use_cases/resolution/resolve_schema.py`
- `src/document_processing/domain/fallback/mapping_plan.py`
- `src/document_processing/application/use_cases/fallback/fragment_generation.py`
- `src/document_processing/application/use_cases/fallback/unit_mapping_prompts.py`
- `src/document_processing/application/use_cases/fallback/candidate_prompts.py`
- `src/document_processing/application/use_cases/fallback/payload_assembly.py`
- `src/document_processing/domain/fallback/candidate_validation.py`
- `docs/plans/plano-dag3-arrays-tabelas-fragmentos.md`
- `docs/plans/plano-escalabilidade-dag3-layout-blocos.md`
