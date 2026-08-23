# Arquitetura de Orquestração Airflow para o Pipeline de Documentos

## Separacao entre coleta e extracao

```text
dag_detecta_e_baixa_pdfs_construtoras
  -> busca RI e grava documentos-origem
  -> dispara dag_extrai_documentos_origem com os manifestos novos

Portal ou operador manual
  -> grava PDF e documento_origem.json em documentos-origem
  -> dispara dag_extrai_documentos_origem

dag_extrai_documentos_origem
  -> recebe manifestos ou varre documentos-origem
  -> chama Docling, persiste extracao e dispara DAG 2
```

A extracao nao depende mais da fonte de RI das construtoras. Isso permite que
qualquer familia documental entre pelo mesmo caminho deterministico.

## Objetivo

Este documento descreve o fluxo completo para:

- detectar novos PDFs no data lake;
- extrair artefatos estruturais e semiestruturados;
- resolver os campos do `schema_saida` definido no contrato semântico;
- validar se o mapeamento canônico ainda funciona;
- acionar fallback com LLM somente quando necessário;
- gerar dados brutos prontos para ingestão na camada bronze.

A extração de construtoras deve priorizar valores brutos observados no PDF, como unidades lançadas e unidades vendidas por período. Percentuais comparativos, variações trimestre contra trimestre, ano contra ano e janelas acumuladas devem ser calculados depois, na engenharia de dados, a partir dos valores brutos resolvidos.

Os arquivos centrais deste fluxo são:

- `contrato_semantico_construtora.json`
- `layout_signature_<empresa>_deterministico.json`

O contrato semântico define **o que precisa sair**.

O layout signature com mapeamento canônico define **onde buscar e como resolver** os campos.


## Visão geral do fluxo

O fluxo recomendado e dividido em cinco DAGs principais.

1. `dag_detecta_e_baixa_pdfs_construtoras`
2. `dag_extrai_documentos_origem`
3. `dag_resolve_schema_saida`
4. `dag_valida_e_fallback_llm`
5. `dag_ingere_bronze`

Em alto nível:

1. um novo PDF entra no data lake;
2. a extração gera artefatos como tabelas, blocos, seções e candidatos textuais;
3. outra DAG usa contrato + layout signature para montar o `schema_saida` com valores brutos;
4. se houver falha crítica, entra o fallback com LLM;
5. o JSON final vai para ingestão na bronze;
6. a engenharia de dados calcula métricas derivadas e segue daí até consumo em BI.


## Artefatos estáticos

### 1. Contrato semântico

Arquivo:

- `contrato_semantico_construtora.json`

Função:

- definir entidades, métricas e sinônimos;
- definir o `schema_saida`;
- estabelecer quais campos são esperados;
- declarar que o resultado canônico deve preservar valores brutos;
- indicar quais métricas derivadas serão calculadas depois;
- separar o significado de negócio do layout do documento.

Esse arquivo não deve ser recalculado a cada execução.
Ele muda quando há decisão explícita de evolução semântica.


### 2. Layout signature com mapeamento canônico

Arquivo:

- `layout_signature_<empresa>_deterministico.json`

Exemplo atual:

- `layout_signature_cury_deterministico.json`

Função:

- apontar caminhos de leitura para o `schema_saida`;
- registrar as fontes relevantes;
- definir regras determinísticas para detectar quebra;
- informar quais campos são resolvidos por tabela, cabeçalho, bloco textual, valor fixo ou derivação;
- mapear períodos por papel semântico, como `periodo_referencia`, `periodo_comparativo_anterior`, `mesmo_periodo_ano_anterior`, `periodo_12m_atual` e `periodo_12m_anterior`, sem prender a regra a um trimestre específico.

Esse arquivo é a referência operacional da DAG de resolução.
Ele não deve conter texto aberto, resumo narrativo ou status de compatibilidade preenchido manualmente.


## DAG 1A: detectar e baixar PDFs de construtoras

### Nome sugerido

- `dag_detecta_e_baixa_pdfs_construtoras`

### Entrada

- data lake com novos PDFs;
- metadados mínimos do arquivo;
- identificação da empresa ou tipo documental, quando disponível.

### Responsabilidades

- consultar as fontes RI configuradas para construtoras;
- baixar e persistir PDFs em `documentos-origem/`;
- registrar `documento_detectado.json`;
- disparar a DAG de extracao somente para manifestos novos.

### Saídas esperadas

PDF de origem e manifesto de deteccao. Esta DAG nao executa Docling.

## DAG 1B: extrair documentos de origem

### Nome

- `dag_extrai_documentos_origem`

### Responsabilidades

- receber manifestos de origem especificos ou varrer `documentos-origem/`;
- selecionar PDFs ainda sem extracao, salvo reprocessamento explicito;
- executar o pipeline Docling;
- persistir artefatos e `manifesto_execucao.json`;
- disparar a DAG 2 para extracoes concluidas.

### Saidas esperadas

Pasta de extracao por documento, com arquivos como:

- `metadata.json`
- `tables/`
- `sections/`
- `blocks/`
- `metrics/`
- `text_candidates/`
- `text_structures/`
- `charts/` quando houver

### Observação

Esta DAG nao gera `schema_saida`; ela so prepara os artefatos para a DAG 2.

O processamento pesado do `docling_pipeline` pode ocorrer em um runner remoto.
Nesse caso, a DAG envia o PDF ao runner, recebe `extraction.tar.gz`, extrai a
pasta localmente e persiste os mesmos artefatos no MinIO. A fronteira entre as
DAGs permanece a pasta de extração já materializada no data lake; as DAGs
seguintes não precisam saber se o Docling rodou localmente ou no Mac Studio.


## DAG 2: resolver schema de saída

### Nome sugerido

- `dag_resolve_schema_saida`

### Entrada

- artefatos da extração gerados pela DAG 1;
- contrato semântico padrão ou `contrato_semantico_uri` informado na execução;
- `layout_signature_<empresa>_deterministico.json`.

### O que esta DAG faz

Essa é a DAG central da arquitetura.

Ela faz três coisas:

1. valida se o layout signature ainda funciona para o PDF atual;
2. resolve os campos do `schema_saida`;
3. gera artefatos de validação e de saída resolvida.

### Como ela escolhe o layout signature correto

Essa DAG precisa carregar o layout signature apropriado para o documento.

Exemplos de critérios de seleção:

- empresa identificada no nome do arquivo;
- empresa identificada em metadados do lote;
- tipo documental identificado em catálogo;
- mapeamento de empresa para arquivo estático.

Exemplo:

- PDF da Cury -> usar `layout_signature_cury_deterministico.json`
- PDF da MRV -> usar `layout_signature_mrv.json` ou futura versão determinística equivalente

Ou seja, “escolher o layout signature correto” significa:

- localizar o arquivo estático que representa o mapa de leitura daquela empresa/tipo documental.

### Etapas internas da DAG

#### 2.1 Validar regras determinísticas

A DAG executa `regras_deteccao_mudanca` do layout signature.

Exemplos de testes:

- `arquivo_existe`
- `secao_existe`
- `linha_existe_em_tabela`
- `perfil_colunas_periodo_existe_em_tabela`
- `valor_normalizavel`

Cada teste retorna algo fechado, por exemplo:

- `passou = true|false`
- `codigo_falha`
- `arquivo_avaliado`
- `valor_observado`

#### 2.2 Percorrer o mapeamento canônico

Para cada chave do `schema_saida`, a DAG executa o método definido em `mapeamento_canonico`.

Exemplos:

- `tipo_origem = valor_fixo`
- `tipo_origem = campo_derivado`
- `tipo_origem = cabecalho_de_tabela`
- `tipo_origem = celula_de_tabela`
- `tipo_origem = bloco_textual`
- `tipo_origem = campo_json`
- `tipo_origem = linhas_de_tabela`
- `tipo_origem = juncao_de_registros_json`
- `tipo_origem = nao_mapeado_neste_documento`
- `tipo_origem = nao_aplicavel_neste_pdf_individual`

#### 2.3 Montar o JSON final

A DAG gera o `schema_saida` preenchido com:

- valores resolvidos;
- `null` quando o contrato permitir;
- ausência controlada quando o campo não se aplica ao documento.

#### 2.4 Leitura estrutural de tabelas e metadados

`linhas_de_tabela` possui dois formatos. O formato semântico usa `campos`
nomeados no layout para preencher diretamente objetos do schema. O formato
estrutural usa apenas
`linha_inicial`, `linha_final`, `segmentos`, `faixas_linhas` e
`indices_colunas`; ele preserva a leitura bruta com índices na auditoria. Os
dois formatos são declarativos: a DAG 2 não conhece nomes de negócio fixos.

`campo_json` lê um valor já materializado em qualquer JSON da extração por
`arquivo_origem` e `caminho_json`. Ele não converte datas nem aplica regras de
empresa. Quando o contrato precisar de limites de período, a origem deve
publicar esses limites no manifesto/metadado normalizado.

### Saídas esperadas

#### A. `validacao_layout_signature.json`

Artefato dinâmico e determinístico.

Ele deve conter algo do tipo:

- `status_compatibilidade`
- `regras_executadas`
- `regras_falharam`
- `campos_resolvidos`
- `campos_nao_resolvidos`
- `codigos_alerta`
- `llm_necessaria`

#### B. `schema_saida_resolvido.json`

JSON final no formato do contrato, pronto para relatório, cálculo posterior ou ingestão.

Esse arquivo contém os valores finais resolvidos. Ele não precisa conter a trilha completa de auditoria de cada célula.

#### C. `auditoria_resolucao.json`

Opcional, mas recomendado.

Serve para rastrear:

- de qual artefato veio cada valor;
- qual seletor foi usado;
- qual era o valor bruto;
- como foi a normalização;
- qual foi o status de resolução.

Ele não faz parte do caminho crítico da ingestão bronze. A ingestão deve consumir `schema_saida_resolvido.json`; a auditoria serve para rastreabilidade, depuração, conferência humana e investigação de divergências.


## DAG 3: fallback com LLM

### Nome sugerido

- `dag_valida_e_fallback_llm`

### Quando essa DAG entra

Ela só precisa ser acionada quando `validacao_layout_signature.json` indicar falha compatível com fallback.

Exemplos:

- tabela crítica ausente;
- linha crítica ausente;
- coluna crítica ausente;
- valor não normalizável;
- ambiguidade entre candidatos;
- campo obrigatório sem resolução.

### O que ela recebe

- `validacao_layout_signature.json`
- artefatos da extração;
- contrato semântico;
- layout signature usado na tentativa anterior;
- opcionalmente o `auditoria_resolucao.json`.

### Escolha do contrato por domínio

A DAG 1 deriva o domínio pelo caminho do PDF em
`documentos-origem/<dominio>/<entidade>/...`. Para cada nova extração, ela
seleciona o contrato da maior versão semântica em `contratos/<dominio>/` e
persiste `contrato_semantico_uri` no `manifesto_execucao.json`. A DAG 2 usa a
URI do manifesto; ao acionar a DAG 3, repassa a mesma URI; a revalidação a
mantém. O contrato só pode ser sobrescrito por `dag_run.conf` explícito em uma
execução manual.

### O que a LLM deve fazer

A LLM não deve regenerar tudo por padrão.

Ela pode propor somente tipos de origem que a DAG 2 executa: `valor_fixo`,
`campo_derivado`, `campo_json`, `bloco_textual`, `cabecalho_de_tabela`,
`celula_de_tabela`, `linhas_de_tabela` e `juncao_de_registros_json`. A escolha
continua limitada aos artefatos recuperados e aos paths declarados pelo contrato
semântico.

Para não assumir o domínio de construtoras, a identidade operacional é
`entity_slug` (com `entity_name` opcional). `company_slug` permanece apenas como
compatibilidade para execuções e manifestos antigos.

A estratégia recomendada é:

1. tentar regenerar **apenas os trechos faltantes ou quebrados** do mapeamento;
2. só regenerar o mapeamento inteiro quando a quebra estrutural for ampla.

### Regra prática recomendada

#### Regenerar apenas o dado faltante quando:

- o problema está em um ou poucos campos;
- a tabela base continua existindo;
- só mudou o nome da linha;
- só mudou o cabeçalho da coluna;
- o conceito ainda é claramente o mesmo.

Exemplos:

- o padrão do cabeçalho de período mudou;
- `Número de Unidades` virou `Unidades`
- `Vendas Líquidas` virou `Vendas Contratadas`

#### Regenerar o mapeamento inteiro quando:

- a tabela principal desapareceu;
- o documento passou a usar outra orientação estrutural;
- o conceito saiu de tabela e foi para texto;
- várias regras críticas falharam ao mesmo tempo;
- a empresa mudou de padrão de relatório de forma ampla.

### Saídas esperadas

#### A. `proposta_novo_mapeamento.json`

Contém apenas as mudanças sugeridas pela LLM.

Estratégia recomendada:

- manter formato parcial, por campo;
- não sobrescrever automaticamente o layout signature base.

#### B. `analise_semantica_llm.json`

Opcional.

Contém:

- justificativa textual;
- evidências consideradas;
- confiança da sugestão;
- recomendação de atualizar parcialmente ou totalmente o mapeamento.

### Observação importante

A LLM deve ser apoio de exceção, não o mecanismo principal de resolução.


## DAG 4: ingestão na bronze

### Nome sugerido

- `dag_ingere_bronze`

### Entrada

- `schema_saida_resolvido.json`

### Responsabilidades

- transformar o JSON final em registros estruturados;
- carregar os dados na camada bronze;
- registrar metadados de execução;
- ligar cada carga ao documento de origem e à resolução usada.

### Saídas esperadas

- tabelas bronze no banco;
- log de ingestão;
- metadados de linhagem.


## Como os artefatos se comunicam

### Comunicação entre DAG 1 e DAG 2

A DAG 1 entrega:

- artefatos de extração

A DAG 2 consome:

- `tables/`
- `sections/`
- `blocks/`
- `text_candidates/`
- `text_structures/`
- `metadata.json`

### Comunicação entre DAG 2 e DAG 3

A DAG 2 entrega:

- `validacao_layout_signature.json`
- `schema_saida_resolvido.json` quando possível
- `auditoria_resolucao.json`

A DAG 3 só entra se o resultado da validação indicar necessidade de fallback.

### Comunicação entre DAG 2 ou DAG 3 e DAG 4

A ingestão bronze só precisa de:

- `schema_saida_resolvido.json`

Se houver fallback, o ideal é também guardar referência a:

- `proposta_novo_mapeamento.json`
- versão do layout signature usada
- `auditoria_resolucao.json`, quando gerado, para rastreabilidade


## Conjunto mínimo de arquivos gerados por execução

### Sempre

- pasta de extração do documento
- `validacao_layout_signature.json`
- `schema_saida_resolvido.json` ou JSON parcial com falhas

### Recomendado

- `auditoria_resolucao.json`

Esse arquivo é recomendado para ambientes de homologação, primeiros ciclos de produção, investigações de qualidade e execuções com fallback. Ele pode ser omitido ou compactado em produção estável, desde que a ingestão preserve metadados mínimos de linhagem.

### Apenas em fallback

- `proposta_novo_mapeamento.json`
- `analise_semantica_llm.json`


## O que fica estático e o que fica dinâmico

### Estáticos

- `contrato_semantico_construtora.json`
- `layout_signature_<empresa>_deterministico.json`

### Dinâmicos por execução

- artefatos de extração
- `validacao_layout_signature.json`
- `schema_saida_resolvido.json`
- `auditoria_resolucao.json`
- `proposta_novo_mapeamento.json` quando houver fallback


## Recomendação de implementação

### Fase 1

Implementar primeiro:

- DAG 1
- DAG 2
- `validacao_layout_signature.json`
- `schema_saida_resolvido.json`

Sem LLM automática no primeiro momento.

### Fase 2

Adicionar:

- `auditoria_resolucao.json`
- fallback com LLM apenas para campos faltantes

### Fase 3

Adicionar:

- política de regeneração total do mapeamento
- revisão humana assistida
- versionamento automatizado do layout signature


## Resumo final

O contrato semântico diz **o que o sistema precisa entregar**.

O layout signature determinístico diz **onde buscar e como resolver**.

A DAG 2 usa os dois para montar o `schema_saida`.

A validação não deve ser narrativa. Ela deve ser determinística.

A LLM só entra quando o processo determinístico falha de forma relevante.

Quando houver fallback, a estratégia recomendada é:

- primeiro corrigir apenas os campos quebrados;
- só regenerar o mapeamento inteiro quando a estrutura do documento tiver mudado amplamente.
