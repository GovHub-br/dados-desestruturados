# Plataforma de Inteligência Documental

Plataforma para transformar PDFs em dados estruturados, auditáveis e
reutilizáveis. O processo separa claramente o significado do dado do formato
de cada documento: o **contrato semântico** define o que deve ser extraído; a
**layout signature** define onde esse dado está na extração; e a resolução
determinística produz o resultado final a partir dessas duas referências.

O projeto é multi-domínio. Construtoras é o domínio de referência inicial, mas
novos tipos de documento podem entrar ao publicar seu próprio contrato
semântico, sem criar regras específicas no código de resolução.

## Visão do fluxo

```text
PDF de origem
  -> extração Docling
  -> artefatos de evidência no MinIO (tabelas, gráficos, blocos e manifesto)
  -> resolução determinística: contrato + layout signature
  -> schema_saida_resolvido + auditoria
  -> ingestão bronze / consumidores

Se o layout estiver ausente ou inválido:
  -> fallback LLM seleciona evidências e propõe layout signature
  -> validação determinística e revalidação
  -> publicação versionada somente se aprovada
```

A LLM não é responsável por calcular indicadores finais nem por publicar dados
diretamente. Ela é usada apenas para propor ou corrigir o mapeamento de layout;
toda proposta volta pela validação determinística antes de ser aceita.

## Componentes

| Componente | Responsabilidade |
| --- | --- |
| `portal/` | Interface para publicar contratos e enviar documentos. |
| `airflow/dags/` | Adaptadores de orquestração: descoberta, extração, resolução, fallback e bronze. |
| `src/document_processing/` | Núcleo independente do domínio, aplicação e infraestrutura. |
| `docling_pipeline/` | Extração de conteúdo e artefatos estruturais do PDF. |
| `infra/` | Dockerfiles, bootstrap do MinIO, OpenMetadata e infraestrutura local. |
| `docs/` | Arquitetura, decisões, guias operacionais e planos. |
| `specs/` | Contexto e especificações versionadas do produto. |
| `skills/` | Procedimentos reutilizáveis para contratos, DAGs e diagnósticos. |

## DAGs principais

| DAG | Papel |
| --- | --- |
| `dag_detecta_e_baixa_pdfs_construtoras` | Descobre e baixa PDFs de RI para documentos de origem. |
| `dag_extrai_documentos_origem` | Varre documentos de origem, chama o Docling e persiste a extração. |
| `dag_resolve_schema_saida` | Resolve o schema de saída usando contrato e layout signature. |
| `dag_valida_e_fallback_llm` | Gera ou corrige layouts quando a resolução falha ou não há layout. |
| `dag_ingere_bronze` | Ingestão dos dados brutos validados na camada bronze. |

As duas primeiras DAGs são desacopladas: um PDF pode vir de RI, do portal ou
de qualquer outro processo que o grave em documentos de origem.

## Conceitos centrais

| Artefato | Finalidade |
| --- | --- |
| Contrato semântico | Declara o schema de saída, campos obrigatórios, contexto e valores literais. É a definição de negócio. |
| Layout signature | Mapeia cada campo do contrato para tabelas, gráficos, blocos ou metadados da extração. É versionada por entidade/documento. |
| Manifesto de execução | Registra, de forma imutável, o PDF, a extração, o contrato e os caminhos de artefatos usados em uma execução. |
| `schema_saida_resolvido` | Resultado bruto resolvido, acompanhado de auditoria e validação. |
| MinIO | Fonte de evidências e armazenamento de artefatos versionados. |

## Início rápido local

1. Copie e preencha as variáveis de ambiente:

   ```bash
   cp .env.example .env
   ```

2. Suba a infraestrutura:

   ```bash
   docker compose up -d --build
   ```

3. Confira o estado dos serviços:

   ```bash
   docker compose ps
   ```

O portal fica disponível em `http://localhost:8000` por padrão. As portas dos
demais serviços, credenciais locais e integrações opcionais são configuradas
no `.env` e no [docker-compose.yml](docker-compose.yml).

O bootstrap do MinIO publica a estrutura base e o contrato semântico de
construtoras. Em produção, contratos e layouts devem continuar sendo
versionados como artefatos explícitos; não dependa da versão interna do
OpenMetadata como versão de negócio.

## Fluxo para um novo domínio documental

1. Defina e publique um contrato semântico do domínio.
2. Envie o PDF pelo portal, ou grave-o na área de documentos de origem.
3. Execute a extração Docling e revise os artefatos de evidência, se necessário.
4. Execute a resolução determinística.
5. Quando não houver layout válido, permita o fallback LLM propor um candidato.
6. Só utilize o schema resolvido após a revalidação e auditoria.

Consulte o guia de [contratos semânticos e layout signatures](docs/guides/semantic-contract-and-layout.md) antes de criar um novo domínio.

## Extração local direta

Para inspecionar um PDF sem acionar as DAGs:

```bash
python3 -m docling_pipeline caminho/para/documento.pdf --output-dir ./saida
```

Os artefatos incluem tabelas, gráficos, blocos, métricas, seções e metadados
de posição (`bbox`) quando disponíveis. O catálogo de saída e os formatos
gerados estão documentados em [Extração Docling](docs/architecture/extracao-textual-estruturada-llm.md).

## Qualidade, auditoria e governança

- O Airflow concentra a observabilidade operacional de execuções, tentativas e falhas.
- O MinIO preserva evidências e manifestos por execução.
- O OpenMetadata cataloga ativos lógicos estáveis — contratos, layouts,
  conjuntos de extrações, dados resolvidos, quarentena, pipelines e tabelas —
  sem criar um ativo de governança para cada PDF ou execução individual.
- A página de auditoria e os manifestos são a fonte de detalhe para uma execução
  específica; o catálogo aponta para elas por links e identificadores.

Leia [Governança e linhagem no OpenMetadata](docs/architecture/governanca-e-linhagem-openmetadata.md) para os limites entre catálogo, observabilidade e histórico operacional.

## Testes e verificações

Valide a organização documental e de skills:

```bash
python scripts/validate_repository_structure.py
```

Para a suíte Python, use o ambiente do projeto:

```bash
pytest tests/unit
```

Os testes específicos de cada domínio e DAG ficam próximos aos módulos
correspondentes em `tests/`.

## Documentação

Comece pelo [índice da documentação](docs/README.md). Ele explica a ordem de
leitura e a finalidade de cada área. Referências principais:

- [Contexto do produto](specs/platform/CONTEXT.md)
- [Especificação da plataforma](specs/platform/SPEC.md)
- [Arquitetura de orquestração Airflow](docs/architecture/arquitetura-orquestracao-airflow.md)
- [Fallback LLM e geração de layout](docs/architecture/fallback-llm-e-geracao-layout-dag3.md)
- [Resolução determinística da DAG 2](docs/architecture/resolucao-deterministica-schema-saida-dag2.md)
- [ADRs](docs/adr/README.md)
- [Guias operacionais](docs/operations/)
- [Skills versionadas](skills/README.md)

## Princípios do projeto

- Extrair valores observados; cálculos e métricas derivadas pertencem às camadas posteriores.
- Manter contratos e layouts explícitos, versionados e auditáveis.
- Usar LLM de forma limitada, observável e sempre sujeita à revalidação.
- Preferir regras genéricas guiadas pelo contrato a condições específicas de um domínio.
- Separar núcleo de negócio, infraestrutura e orquestração para permitir evolução sem acoplamento ao Airflow.
