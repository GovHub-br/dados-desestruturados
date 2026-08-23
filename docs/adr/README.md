# Architecture Decision Records

Este diretório registra decisões arquiteturais duradouras. ADRs não substituem
guias operacionais ou planos de trabalho: explicam o contexto, a decisão e as
consequências que devem continuar válidas enquanto o projeto evolui.

| ADR | Status | Decisão |
| --- | --- | --- |
| [0001](0001-versionamento-de-contratos-e-layouts-no-minio.md) | Aceito | Contratos semânticos e layouts são artefatos versionados no MinIO. |
| [0002](0002-publicacao-apos-revalidacao-deterministica.md) | Aceito | Um layout candidato só é publicado após revalidação determinística. |
| [0003](0003-separacao-descoberta-e-extracao.md) | Aceito | Descoberta/download e extração de PDFs são fluxos separados. |
| [0004](0004-resolucao-deterministica-com-fallback-llm.md) | Aceito | A resolução é determinística; LLM é fallback controlado. |
| [0005](0005-contrato-declara-requisitos-e-literais.md) | Aceito | O contrato declara requisitos de mapeamento e valores literais. |
| [0006](0006-openmetadata-cataloga-ativos-logicos.md) | Aceito | OpenMetadata cataloga ativos lógicos, não ocorrências de execução. |
| [0007](0007-portal-como-fronteira-autenticada.md) | Aceito | O portal é a fronteira autenticada para operações de usuários. |
| [0008](0008-nucleo-independente-e-airflow-adaptador.md) | Aceito | O núcleo deve ser independente; Airflow é adaptador de orquestração. |

