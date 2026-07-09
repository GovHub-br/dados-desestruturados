# Implementacoes Futuras

Este documento registra ideias e melhorias futuras que ainda nao fazem parte do
fluxo principal implementado, mas que devem permanecer visiveis para evolucao do
pipeline.

## Ingestao Automatica de Contrato Semantico

Hoje o contrato semantico precisa ser inserido manualmente no MinIO antes da
execucao das DAGs. Como o contrato e a principal entrada manual do usuario, uma
melhoria futura e criar uma DAG dedicada para publicar automaticamente contratos
semanticos versionados a partir de uma pasta controlada no repositorio.

### Objetivo

Permitir que o usuario adicione um contrato semantico em uma pasta especifica do
repositorio e que o Airflow publique esse contrato no MinIO com validacao,
versionamento e rastreabilidade.

Exemplo de pasta local:

```text
dados-desestruturados/contratos_semanticos/
```

Exemplo de destino no MinIO:

```text
contratos/construtoras/v1.3.0/contrato_semantico_construtora.json
```

### Fluxo Desejado

1. Usuario adiciona ou altera um contrato semantico no repositorio.
2. Uma DAG identifica o arquivo novo ou alterado.
3. A DAG valida a estrutura minima do contrato.
4. A DAG calcula hash do arquivo.
5. A DAG verifica se aquela versao/hash ja foi publicada.
6. A DAG publica o contrato em um caminho versionado no MinIO.
7. A DAG atualiza um registro de ingestao, por exemplo `registry.json`.

### Validacoes Minimas

O contrato deve conter, no minimo:

- `nome`;
- `versao`;
- `dominio`;
- `schema_saida`;
- `entidades`;
- `metricas`.

### Opcao 1: DAG com Polling

A DAG roda periodicamente, por exemplo a cada 1 ou 5 minutos, escaneando a pasta
local de contratos.

Vantagens:

- simples de implementar;
- funciona bem com Airflow;
- nao depende de webhook externo;
- facil de debugar localmente.

Desvantagens:

- nao e instantaneo;
- depende de uma frequencia de agendamento.

### Opcao 2: FileSensor

A DAG usa um sensor para aguardar arquivos em uma pasta especifica.

Vantagens:

- mais proximo de um comportamento orientado a evento;
- Airflow ja possui primitivos para sensores de arquivo.

Desvantagens:

- menos flexivel para multiplos arquivos, versoes e hashes;
- pode ficar mais dificil controlar idempotencia;
- pode manter tasks em espera por muito tempo.

### Opcao 3: Git/CI Dispara a DAG

Uma pipeline externa, como GitHub Actions, dispara a DAG quando um contrato novo
e versionado no repositorio.

Vantagens:

- mais alinhado com GitOps;
- permite validar contrato antes do merge;
- melhora rastreabilidade de quem alterou o contrato.

Desvantagens:

- exige integracao externa;
- depende de API/autenticacao do Airflow;
- aumenta a complexidade operacional.

### Registro de Ingestao

Uma possibilidade e manter um artefato de registro no MinIO:

```text
contratos/construtoras/registry.json
```

Exemplo:

```json
{
  "contratos": [
    {
      "dominio": "construtoras",
      "versao": "1.3.0",
      "object_key": "contratos/construtoras/v1.3.0/contrato_semantico_construtora.json",
      "sha256": "...",
      "ingerido_em": "..."
    }
  ]
}
```

Esse registro ajudaria a tornar a ingestao idempotente e auditavel.

## Revisao Humana de Layout Candidato

Por enquanto, a correcao do layout signature fica automatizada: a LLM gera o
layout signature candidato, a DAG 3 valida e materializa esse candidato, a DAG 2
revalida deterministicamente e, se passar, a DAG 3 publica uma nova versao
versionada no MinIO.

A revisao humana pode ser adicionada depois como uma trava opcional antes da
publicacao da nova versao. Essa decisao ainda precisa definir:

- quando a revisao humana sera obrigatoria;
- quais campos um revisor podera aprovar ou rejeitar;
- onde o estado de aprovacao sera persistido;
- como a versao aprovada sera marcada como vigente;
- quais perfis ou papeis poderao homologar um layout candidato.
