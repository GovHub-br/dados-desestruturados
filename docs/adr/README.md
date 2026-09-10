# Registros de Decisão Arquitetural (ADRs)

Status: vigente

Responsável: Mateus de Castro

Última revisão: 2026-08-23

Este diretório registra decisões arquiteturais duradouras. Cada ADR explica
contexto, alternativas, decisão, consequências e critérios para reconsideração.
ADRs não substituem specs, guias ou planos: registram por que uma escolha
arquitetural continua válida enquanto o projeto evolui.

Para alterar uma decisão aceita, crie uma ADR nova como `Proposto`; ao aceitá-la,
marque a ADR anterior como `Substituído`, sem reescrever seu histórico.

| ADR | Data efetiva | Status | Decisão |
| --- | --- | --- | --- |
| [0001](0001-versionamento-de-contratos-e-layouts-no-minio.md) | 2026-06-24 | Aceito | Contratos semânticos e layouts são artefatos versionados no MinIO. |
| [0002](0002-publicacao-apos-revalidacao-deterministica.md) | 2026-06-24 | Aceito | Um layout candidato só é publicado após revalidação determinística. |
| [0003](0003-separacao-descoberta-e-extracao.md) | 2026-08-16 | Aceito | Descoberta/download e extração de PDFs são fluxos separados. |
| [0004](0004-resolucao-deterministica-com-fallback-llm.md) | 2026-06-23 | Aceito | A resolução é determinística; LLM é fallback controlado. |
| [0005](0005-contrato-declara-requisitos-e-literais.md) | 2026-08-03 | Aceito | O contrato declara requisitos de mapeamento e valores literais. |
| [0006](0006-openmetadata-cataloga-ativos-logicos.md) | 2026-08-23 | Aceito | OpenMetadata cataloga ativos lógicos, não ocorrências de execução. |
| [0007](0007-portal-como-fronteira-autenticada.md) | 2026-08-16 | Aceito | O portal é a fronteira autenticada para operações de usuários. |
| [0008](0008-nucleo-independente-e-airflow-adaptador.md) | 2026-08-23 | Aceito | O núcleo deve ser independente; Airflow é adaptador de orquestração. |
| [0009](0009-observabilidade-por-projecao-de-artefatos.md) | 2026-09-05 | Aceito | Observabilidade é feita projetando artefatos persistidos para o Langfuse. |
| [0010](0010-prompts-versionados-no-langfuse.md) | 2026-09-05 | Aceito | Os prompts do fallback são versionados no Langfuse, por bloco e por conjunto. |
