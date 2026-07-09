# Spec do Projeto de Extracao de Construtoras

## Objetivo

Esta especificacao define o comportamento esperado do fluxo de extracao,
resolucao semantica, validacao, fallback e publicacao estruturada de dados de
construtoras a partir de PDFs trimestrais de resultados operacionais.

O projeto deve transformar documentos de RI em um `schema_saida_resolvido.json`
estavel, baseado em valores brutos observados no PDF, pronto para ingestao na
camada bronze. Percentuais comparativos e metricas derivadas devem ser
calculados depois, fora da etapa de resolucao documental.

## Escopo

### Dentro do escopo

- detectar PDFs trimestrais de construtoras em fontes de RI;
- armazenar documentos de origem e artefatos no MinIO;
- extrair artefatos estruturais e semiestruturados com Docling;
- resolver o `schema_saida` definido pelo contrato semantico;
- validar deterministicamente se o layout conhecido continua compativel;
- acionar fallback com LLM quando a resolucao deterministica nao for suficiente;
- gerar layout signature candidato para validacao automatica;
- publicar automaticamente apenas candidatos aprovados por revalidacao rigorosa da DAG 2;
- ingerir `schema_saida_resolvido.json` na camada bronze;
- manter rastreabilidade operacional em Postgres e governanca no OpenMetadata.

### Fora do escopo

- usar OpenMetadata como repositorio primario dos JSONs;
- usar LLM como mecanismo padrao de resolucao;
- calcular percentuais comparativos dentro da DAG de resolucao;
- promover automaticamente layout gerado por LLM para uso recorrente;
- tratar `schema_saida_resolvido.json` como tabela analitica final;
- sobrescrever artefatos historicos de execucoes anteriores.

## Linguagem Canonica

A linguagem canonica do projeto esta em:

- `CONTEXT.md`

Termos desta spec devem seguir esse glossario. Em especial:

- **Contrato Semantico** define o que precisa sair;
- **Layout Signature** define onde e como buscar;
- **Mapeamento Canonico** liga o contrato as fontes observaveis;
- **Schema de Saida Resolvido** e a instancia preenchida do schema para uma execucao;
- **Valor Bruto Observado** e o valor reportado diretamente pelo PDF;
- **Metrica Derivada** e calculada posteriormente;
- **Layout Signature Candidato** pode ser usado em validacao automatica;
- **Layout Signature Ativo** exige revalidacao deterministica completa e publicacao versionada;
- **Ruptura Estrutural Ampla** autoriza regeneracao total de mapeamento.

## Principios

1. O contrato semantico e a fonte de verdade do formato de saida.
2. O layout signature e a fonte de verdade operacional para localizar valores.
3. A DAG de resolucao deve priorizar determinismo, rastreabilidade e repetibilidade.
4. O `schema_saida_resolvido.json` deve conter apenas o que o contrato declara.
5. Valores brutos observados devem ser preservados antes de qualquer calculo.
6. Percentuais comparativos presentes no PDF podem ser evidencias de layout, mas nao entram no `schema_saida_resolvido`.
7. Fallback com LLM deve corrigir excecoes, nao substituir o fluxo deterministico.
8. Reprocessamentos devem criar novas execucoes, nao sobrescrever evidencias.
9. OpenMetadata governa e cataloga; MinIO e Postgres continuam sendo as fontes operacionais.
10. MinIO guarda os artefatos; Postgres operacional guarda estado, linhagem, resumos e ponteiros para esses artefatos.

## Arquitetura Logica

```text
Fontes de RI
  -> DAG 1: detectar PDF e extrair
  -> MinIO: documento de origem + artefatos Docling
  -> Postgres: documento, execucao DAG 1 e ponteiros de artefatos
  -> DAG 2: validar layout e resolver schema_saida
  -> MinIO: validacao + schema resolvido + auditoria
  -> Postgres: execucao DAG 2, status de validacao e ponteiros de resolucao
  -> DAG 3: fallback com LLM, quando necessario
  -> DAG 2: nova execucao com layout candidato, quando houver fallback
  -> DAG 4: ingestao bronze
  -> Postgres: estado operacional, linhagem e resumos
  -> OpenMetadata: catalogo, glossario, ownership e lineage
```

## Artefatos Estaticos

### `contrato_semantico_construtora.json`

Define:

- conceitos canonicos;
- sinonimos;
- entidades;
- metricas brutas;
- derivacoes previstas;
- `schema_saida`;
- quais valores pertencem ou nao a resolucao documental.

O contrato semantico nao deve conter seletores de layout nem paths fisicos de
artefatos de extracao.

### `layout_signature_<empresa>_deterministico.json`

Define:

- empresa e tipo documental;
- referencia ao contrato semantico;
- fontes relevantes;
- regras deterministicas de deteccao de mudanca;
- mapeamento canonico para os campos do `schema_saida`;
- regras de execucao, incluindo uso de aliases e fallback.

O layout signature pode conhecer colunas e estruturas que ajudam a validar o
layout, mas o `mapeamento_canonico` nao deve prometer campos que nao pertencem
ao `schema_saida_resolvido`.

## Artefatos Dinamicos

Artefatos dinamicos vivem fisicamente no MinIO. O Postgres operacional deve
registrar ponteiros, status e resumos suficientes para operar o pipeline sem
abrir todos os JSONs, mas nao deve ser o repositorio primario desses arquivos.

### `validacao_layout_signature.json`

Resultado deterministico por execucao.

Deve informar:

- status de compatibilidade;
- regras executadas;
- regras aprovadas e reprovadas;
- codigos de falha;
- se a ingestao pode continuar;
- se fallback deve ser acionado.

Esse arquivo decide se o processo segue para bronze ou para fallback.

### `schema_saida_resolvido.json`

Produto canonicamente consumivel da DAG 2.

Pode ser gerado mesmo quando a validacao indicar falha, mas nesse caso deve ser
tratado como parcial ou incompleto. A DAG 4 so pode consumir esse artefato
quando a validacao permitir continuidade ou quando houver fallback homologado.

Deve conter:

- `fonte`;
- `periodo_referencia`;
- `periodos_disponiveis`;
- `balancos_das_empresas.lancamentos`;
- `balancos_das_empresas.vendas`;
- `metricas_calculadas` apenas como declaracao de que nao foram calculadas na extracao.

Nao deve conter:

- `%T/T`;
- `%A/A`;
- variacoes percentuais resolvidas do PDF;
- campos nao declarados no contrato;
- auditoria detalhada de origem de celulas.

### `auditoria_resolucao.json`

Artefato recomendado para rastreabilidade.

Pode conter:

- fonte usada por campo;
- seletor aplicado;
- valor bruto encontrado;
- valor normalizado;
- status de resolucao;
- evidencias auxiliares.

Nao faz parte do caminho critico de ingestao bronze.

### `proposta_novo_mapeamento.json`

Artefato de fallback.

Deve conter somente as mudancas sugeridas quando possivel. Por padrao, a
proposta deve ser parcial e focada nos campos quebrados.

### `analise_semantica_llm.json`

Artefato opcional de fallback.

Pode conter:

- justificativa textual;
- evidencias consideradas;
- confianca;
- recomendacao de correcao parcial ou regeneracao total.

### `manifesto_execucao.json`

Indice operacional produzido por uma DAG para tornar a execucao reprocessavel.

Deve conter, conforme a DAG:

- `execution_id`;
- `document_id`;
- empresa/entidade;
- periodo ou metadados do documento;
- URI do documento de origem, quando aplicavel;
- prefixo dos artefatos;
- lista de `artifact_uris`;
- resultado do runner ou etapa executada;
- dados minimos para a proxima DAG localizar os artefatos corretos.

O manifesto nao substitui o Postgres operacional. Ele e um artefato de MinIO
que permite reprocessamento e portabilidade. O Postgres deve registrar o mesmo
`execution_id`, os status operacionais e os ponteiros principais para consulta
rapida.

## Periodos

Os documentos tratados por este fluxo sao relatorios trimestrais. Portanto, os
papeis de periodo sao resolvidos uma vez para o documento inteiro.

Papeis esperados:

- `periodo_referencia`;
- `periodo_comparativo_anterior`;
- `mesmo_periodo_ano_anterior`;
- `periodo_12m_atual`;
- `periodo_12m_anterior`.

Se fontes criticas divergirem sobre esses papeis, a situacao deve ser tratada
como ruptura estrutural ampla.

## Valores Brutos e Metricas Derivadas

O `schema_saida_resolvido.json` deve preservar somente valores brutos observados.

Exemplos de valores que entram:

- unidades lancadas por periodo;
- unidades vendidas por periodo;
- valores UDM quando reportados como valor bruto.

Exemplos de valores que nao entram:

- `%T/T`;
- `%A/A`;
- variacao trimestre contra trimestre;
- variacao contra mesmo periodo do ano anterior;
- variacao entre janelas de 12 meses.

Esses percentuais podem aparecer nos artefatos de extracao e na auditoria como
evidencias observaveis do PDF, mas nao pertencem ao `schema_saida_resolvido`.

## DAG 1: Detectar PDF e Extrair

Nome esperado:

- `dag_detecta_pdf_e_extrai`

Responsabilidades:

- identificar a janela trimestral ativa;
- detectar PDFs candidatos nas fontes de RI;
- persistir PDFs no MinIO;
- executar Docling em runtime dedicado;
- persistir artefatos de extracao.
- registrar documento, execucao e artefatos no Postgres operacional quando a
  integracao operacional estiver implementada.

Saidas:

- documento de origem;
- `metadata.json`;
- `sections/`;
- `blocks/`;
- `tables/`;
- `metrics/`;
- `charts/`;
- `text_candidates/`;
- `text_structures/`, quando aplicavel.

Nao deve:

- gerar `schema_saida_resolvido`;
- aplicar contrato semantico;
- decidir fallback de resolucao.

## DAG 2: Validar Layout e Resolver Schema de Saida

Nome esperado:

- `dag_resolve_schema_saida`

Entradas:

- artefatos da DAG 1;
- contrato semantico;
- layout signature ativo ou candidato;
- metadados de execucao.

Responsabilidades:

- carregar contrato e layout signature corretos;
- executar regras deterministicas;
- resolver papeis de periodo;
- resolver valores brutos do `schema_saida`;
- gerar validacao;
- gerar `schema_saida_resolvido`;
- gerar auditoria quando configurado.
- registrar execucao, validacao e ponteiros dos artefatos de resolucao no
  Postgres operacional quando a integracao operacional estiver implementada.

Regras:

- a resolucao padrao deve ser deterministica;
- LLM nao participa do caminho normal;
- `schema_saida_resolvido` pode ser gerado em estado parcial;
- `validacao_layout_signature` decide se DAG 4 pode continuar;
- divergencia de periodos entre fontes criticas e ruptura estrutural ampla.

## DAG 3: Fallback com LLM

Nome esperado:

- `dag_valida_e_fallback_llm`

Entradas:

- `validacao_layout_signature.json`;
- artefatos de extracao;
- contrato semantico;
- layout signature usado;
- auditoria de resolucao, quando existir.

Responsabilidades:

- analisar falhas autorizadas para fallback;
- propor correcao parcial de mapeamento por padrao;
- propor regeneracao total apenas em ruptura estrutural ampla;
- materializar layout signature candidato;
- disparar ou permitir nova execucao da DAG 2 com o candidato.
- registrar evento de fallback, escopo de correcao, status e ponteiros dos
  artefatos de fallback no Postgres operacional quando a integracao operacional
  estiver implementada.

Nao deve:

- promover layout candidato para ativo;
- sobrescrever layout signature ativo;
- corrigir diretamente a bronze;
- usar LLM como resolucao padrao.

## Correcao Parcial vs Regeneracao Total

### Correcao parcial

Padrao para fallback.

Usar quando:

- uma linha foi renomeada;
- um cabecalho bruto mudou levemente;
- uma tabela mudou de pagina mas continua reconhecivel;
- um valor isolado ficou nao normalizavel;
- poucos campos obrigatorios falharam.

### Regeneracao total

Usar somente em ruptura estrutural ampla.

Ocorre quando:

- tabela critica esta ausente;
- secao critica esta ausente;
- varios campos obrigatorios falham ao mesmo tempo;
- conceito mudou de tabela para texto, cards ou outra representacao;
- papeis de periodo nao podem ser resolvidos com seguranca;
- fontes criticas discordam sobre os periodos do documento.

## Layout Candidato e Homologacao

Fallback pode gerar e usar automaticamente um layout signature candidato em uma
execucao de validacao.

Esse candidato somente pode virar layout signature ativo depois de revalidacao
deterministica completa; curadoria humana permanece opcional.

Fluxo esperado:

1. DAG 2 falha ou fica incompleta.
2. `validacao_layout_signature` indica fallback.
3. DAG 3 gera `proposta_novo_mapeamento`.
4. Um layout signature candidato e materializado.
5. DAG 2 roda novamente com o candidato.
6. Se todos os gates de cobertura, regras, resolucao e schema passarem, a DAG 3 publica nova versao.
7. O ponteiro ativo e atualizado apenas depois da promocao dos artefatos oficiais.

Esta decisao esta registrada em:

- `docs/adr/0001-fallback-produz-layout-candidato.md`

## DAG 4: Ingestao Bronze

Nome esperado:

- `dag_ingere_bronze`

Entrada:

- `schema_saida_resolvido.json`;
- status de validacao que permita continuidade;
- metadados de execucao.

Responsabilidades:

- transformar JSON resolvido em registros estruturados;
- gravar camada bronze;
- preservar referencia ao documento, execucao, contrato e layout;
- preparar base para calculo posterior de metricas derivadas.
- registrar carga bronze e lineage operacional no Postgres operacional quando a
  integracao operacional estiver implementada.

Nao deve:

- reinterpretar PDF;
- consultar Docling diretamente;
- aceitar schema parcial quando a validacao bloqueou continuidade;
- calcular metricas derivadas como se fossem valores extraidos.

## MinIO

MinIO e o repositorio fisico dos artefatos.

Areas esperadas:

- `contratos/`;
- `layouts/`;
- `documentos-origem/`;
- `execucoes/`;
- `fallback/`;
- `curadoria/`.

Regra:

- reprocessamentos devem gerar novo `execution_id`;
- artefatos historicos nao devem ser sobrescritos.

## Postgres Operacional

Postgres e o catalogo operacional e de linhagem. Ele nao armazena os artefatos
pesados nem substitui o MinIO. Ele armazena registros normalizados, resumos e
ponteiros para os objetos persistidos no MinIO.

Estado atual da implementacao:

- a infraestrutura `postgres-operacional` existe no Docker;
- o init cria schemas `operacional`, `governanca` e `bronze`;
- as tabelas iniciais existem ou estao documentadas;
- o client atual de metadados monta registros em memoria;
- as DAGs ainda nao persistem esses registros no Postgres operacional.

Deve responder:

- qual documento entrou;
- qual execucao processou o documento;
- quais artefatos foram gerados;
- qual contrato foi usado;
- qual layout signature foi usado;
- qual status de validacao foi produzido;
- se houve fallback;
- se a execucao pode seguir para bronze.

Entidades esperadas:

- `documentos`;
- `execucoes_pipeline`;
- `artefatos_execucao`;
- `contratos_semanticos`;
- `layout_signatures`;
- `validacoes_layout`;
- `fallback_execucoes`.

Regra de armazenamento:

- MinIO guarda documentos, manifestos e JSONs completos;
- Postgres guarda `document_id`, `execution_id`, status, versoes, timestamps,
  resumos de validacao e ponteiros `bucket_name`/`object_key`;
- Postgres pode guardar snapshots pequenos e campos agregados para consulta,
  mas nao deve guardar PDF, tabelas completas, `cells.json` ou auditorias
  volumosas como fonte primaria.

Eventos minimos por DAG:

- DAG 1: criar/atualizar `documentos`, criar `execucoes_pipeline`, registrar
  `artefatos_execucao` para PDF, manifesto e pasta de extracao;
- DAG 2: criar `execucoes_pipeline`, registrar artefatos de validacao, schema e
  auditoria, preencher `validacoes_layout`;
- DAG 3: criar `fallback_execucoes`, registrar proposta, analise LLM e layout
  candidato;
- DAG 4: registrar carga bronze e relacionar os registros bronze ao
  `schema_saida_resolvido` aprovado.

Decisoes pendentes:

- se o registro operacional sera feito dentro de cada task ou em tasks finais
  de auditoria por DAG;
- politica de idempotencia para `execution_id` ja existente;
- se falhas parciais devem gravar registros imediatamente ou apenas no fim da
  DAG;
- quais resumos pequenos de JSON devem ser duplicados no Postgres para consulta
  operacional;
- como registrar homologacao humana de layout candidato.

## OpenMetadata

OpenMetadata e a camada de governanca, catalogo, descoberta e lineage.

Deve governar:

- dominios;
- owners;
- glossarios;
- classificacoes;
- pipelines;
- data products;
- tabelas bronze/silver/gold;
- referencias a contratos e layouts.

Nao deve ser:

- repositorio primario de JSONs;
- motor de orquestracao;
- banco operacional detalhado;
- substituto do contrato semantico ou layout signature.

## Criterios de Aceite

### Resolucao bem-sucedida

Uma execucao de DAG 2 e considerada apta para ingestao quando:

- contrato semantico foi carregado;
- layout signature correto foi carregado;
- regras obrigatorias foram aprovadas;
- papeis de periodo foram resolvidos de forma consistente;
- valores brutos obrigatorios foram resolvidos ou tratados conforme contrato;
- `validacao_layout_signature` permite continuidade;
- `schema_saida_resolvido` respeita o contrato;
- nenhum percentual comparativo foi incluido como campo resolvido.
- Postgres operacional registra a execucao, a validacao e os ponteiros dos
  artefatos, quando a integracao operacional estiver implementada.

### Fallback bem-sucedido

Uma execucao de fallback e considerada bem-sucedida quando:

- gera proposta de novo mapeamento;
- materializa layout signature candidato;
- nova execucao de DAG 2 com candidato passa na validacao;
- candidato fica separado do layout signature ativo;
- promocao para ativo ocorre somente apos gate rigoroso e publicacao imutavel.

### Ingestao bronze bem-sucedida

Uma ingestao bronze e considerada bem-sucedida quando:

- consome apenas `schema_saida_resolvido` autorizado pela validacao;
- preserva metadados de documento e execucao;
- referencia contrato e layout usados;
- nao depende de auditoria detalhada para produzir registros;
- deixa metricas derivadas para etapa posterior.
- registra no Postgres operacional a carga e o lineage para a execucao
  aprovada.

## Pendencias e Evolucao

Pendencias naturais:

- implementar persistencia real no Postgres operacional para as DAGs;
- definir contrato de idempotencia das tabelas operacionais;
- decidir quais resumos dos artefatos ficam duplicados no Postgres;
- formalizar schema fisico das tabelas bronze;
- definir processo de homologacao humana de layout candidato;
- definir politica de versionamento para layout signature ativo;
- definir quando auditoria de resolucao e obrigatoria;
- criar testes automatizados para divergencia de periodos;
- criar testes automatizados para impedir percentuais no `schema_saida_resolvido`;
- decidir se a regra de valores brutos merece ADR propria.

## Referencias

- `CONTEXT.md`
- `docs/adr/0001-fallback-produz-layout-candidato.md`
- `resultados_contrutoras/contrato_semantico_construtora.json`
- `resultados_contrutoras/layout_signature_cury_deterministico.json`
- `resultados_contrutoras/documentacao/ARQUITETURA_DAGS_CONSTRUTORAS.md`
- `resultados_contrutoras/documentacao/MODELO_PASTAS_MINIO.md`
- `resultados_contrutoras/documentacao/SCHEMA_INICIAL_POSTGRES.md`
- `resultados_contrutoras/documentacao/ESTUDO_OPENMETADATA_GOVERNANCA.md`
- `resultados_contrutoras/documentacao/EXPLICACAO_LAYOUT_SIGNATURE_CURY_DETERMINISTICO.md`
