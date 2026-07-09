# Documentos Desestruturados

Contexto de extracao, resolucao semantica e governanca de documentos nao estruturados. O projeto separa documentos de origem, artefatos de extracao, resolucao deterministica, fallback assistido e publicacao estruturada.

## Language

**Documento de Origem**:
PDF bruto recebido antes da extracao, tratado como a entrada logica do fluxo documental.
_Avoid_: arquivo bruto, PDF processado

**Artefato de Extracao**:
Resultado intermediario produzido a partir do documento de origem para preservar estrutura, texto, tabelas, graficos, metricas e candidatos textuais.
_Avoid_: dado final, schema de saida

**Manifesto de Execucao**:
Artefato JSON que funciona como indice/recibo de uma execucao, ligando documento, execution_id, artefatos gerados, URIs no MinIO e metadados operacionais.
_Avoid_: artefato extraido, conteudo da extracao, banco operacional

**Contrato Semantico**:       
Artefato versionado que define os conceitos canonicos, sinonimos, campos esperados e regras semanticas de uma familia documental.
_Avoid_: contrato de dados, layout signature

**Layout Signature**:
Artefato versionado que define onde e como encontrar os campos esperados em uma familia documental.
_Avoid_: contrato semantico, relatorio de validacao

**Layout Signature Candidato**:
Layout signature gerado ou ajustado para uma execucao de validacao, ainda sem aprovacao para uso recorrente.
_Avoid_: layout signature ativo, layout homologado

**Layout Signature Ativo**:
Layout signature homologado para uso recorrente na resolucao deterministica de uma familia documental.
_Avoid_: proposta de novo mapeamento, layout temporario

**Mapeamento Canonico**:
Parte do layout signature que liga os campos esperados pelo contrato semantico as fontes observaveis no documento.
_Avoid_: schema de saida, parsing livre

**Schema de Saida**:
Estrutura final esperada pelo contrato semantico depois da resolucao dos campos do documento.
_Avoid_: tabela bronze, artefato de extracao

**Schema de Saida Resolvido**:
Instancia preenchida do schema de saida para uma execucao, pronta para consumo pela ingestao estruturada.
_Avoid_: auditoria de resolucao, validacao de layout

**Valor Bruto Observado**:
Valor reportado diretamente pelo documento e preservado sem calculo analitico pelo processo de resolucao.
_Avoid_: metrica derivada, percentual calculado

**Metrica Derivada**:
Valor calculado posteriormente a partir de valores brutos observados.
_Avoid_: valor bruto observado, dado extraido

**Periodo de Referencia**:
Periodo principal reportado pelo documento trimestral, usado como base para os valores atuais e suas comparacoes.
_Avoid_: data de ingestao, data de execucao

**Papeis de Periodo**:
Conjunto de funcoes temporais fixas no documento trimestral, incluindo periodo de referencia e periodos comparativos.
_Avoid_: cabecalhos isolados, periodos por tabela

**Validacao de Layout Signature**:
Resultado deterministico que indica se o layout signature conhecido continua compativel com o documento processado.
_Avoid_: auditoria de resolucao, analise semantica

**Auditoria de Resolucao**:
Trilha que explica a origem e a interpretacao dos valores resolvidos.
_Avoid_: schema de saida resolvido, relatorio final

**Fallback com LLM**:
Processo assistido por LLM acionado quando a resolucao deterministica nao resolve um campo ou detecta ruptura relevante.
_Avoid_: resolucao padrao, extracao principal

**Proposta de Novo Mapeamento**:
Sugestao de ajuste no mapeamento canonico produzida quando a resolucao deterministica nao e suficiente.
_Avoid_: schema de saida resolvido, layout homologado

**Correcao Parcial de Mapeamento**:
Ajuste focado nos campos ou seletores quebrados, preservando o restante do layout signature conhecido.
_Avoid_: regeneracao total, novo layout completo

**Regeneracao Total de Mapeamento**:
Criacao de um novo mapeamento amplo quando a estrutura documental deixa de corresponder ao layout signature conhecido.
_Avoid_: correcao pontual, ajuste de alias

**Ruptura Estrutural Ampla**:
Mudanca documental que impede confiar no layout signature conhecido, como ausencia de secao ou tabela critica, falha simultanea de varios campos obrigatorios, troca da representacao de um conceito, perda dos papeis de periodo ou divergencia de periodos entre fontes criticas.
_Avoid_: linha renomeada, cabecalho levemente alterado

**Camada Bronze**:
Primeira camada estruturada derivada do schema de saida resolvido.
_Avoid_: schema de saida resolvido, artefato bruto

**Postgres Operacional**:
Banco de catalogo operacional, estado e linhagem das execucoes, contendo registros resumidos e ponteiros para artefatos no MinIO.
_Avoid_: data lake, repositorio de JSON bruto, armazenamento principal de artefatos

**Registro Operacional de Execucao**:
Linha ou conjunto de linhas que descreve uma execucao de DAG, seu status, documento, contrato, layout, validacao, fallback e artefatos associados.
_Avoid_: manifesto de execucao, log textual, artefato bruto

**Ponteiro de Artefato**:
Referencia operacional a um artefato persistido, normalmente composta por bucket, object_key, tipo de artefato, execution_id e metadados de integridade.
_Avoid_: conteudo do arquivo, blob, JSON completo

**Curadoria**:
Revisao, evidencia ou homologacao humana associada a contratos, layouts, fallback ou qualidade dos dados resolvidos.
_Avoid_: fallback automatico, validacao deterministica
