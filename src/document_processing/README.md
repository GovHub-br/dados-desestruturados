# Núcleo de Processamento Documental

`document_processing` é a biblioteca principal da plataforma. Ela contém as
regras reutilizáveis para processar documentos, independente de Airflow,
portal, Docling ou de um domínio específico de PDFs.

As DAGs em `airflow/dags/` são adaptadores de orquestração: montam dependências,
recebem configurações e chamam os casos de uso deste pacote. Novas interfaces
(API, worker, CLI ou outro orquestrador) devem reutilizar este núcleo em vez de
copiar regras para suas próprias camadas.

## Organização

```text
document_processing/
├── domain/           # regras puras, modelos e validações de negócio
├── application/      # casos de uso e portas para dependências externas
├── infrastructure/   # adaptadores concretos: MinIO, LLM, Docling, RI e governança
└── shared/           # configuração e utilitários técnicos compartilhados
```

### `domain/`

Camada sem dependência de Airflow, MinIO ou HTTP. É onde ficam os conceitos que
precisam continuar verdadeiros para qualquer domínio documental:

- contratos semânticos e requisitos de mapeamento;
- paths e regras de layouts;
- classificação e validação de fallback;
- modelos de candidato e seleção de artefatos;
- normalização de números e regras de resolução.

Uma função nesta camada não deve abrir arquivos, chamar uma API ou consultar
variáveis de ambiente.

### `application/`

Orquestra regras do domínio para atender um caso de uso. Seus subdiretórios
principais são:

- `use_cases/documents/`: armazenamento de documento de origem e extração;
- `use_cases/resolution/`: carregamento de manifesto, resolução determinística,
  auditoria e publicação do schema de saída;
- `use_cases/fallback/`: contexto, seleção de evidências, geração e validação de
  candidatos de layout via LLM;
- `ports/`: contratos que descrevem dependências externas necessárias aos casos
  de uso.

Esta camada pode depender de interfaces/portas e do domínio. Ela não deve
conhecer detalhes de uma DAG, operador Airflow ou rota HTTP.

### `infrastructure/`

Implementa as dependências externas usadas pela aplicação:

- `storage/`: MinIO e registro de contratos semânticos;
- `llm/`: cliente LLM e transporte HTTP;
- `docling/`: gateway para o runtime de extração;
- `ri/`: consulta de resultados de relações com investidores;
- `governance/`: integração com metadados operacionais e governança.

Adaptadores desta camada devem manter detalhes de protocolo, autenticação,
serialização e tratamento de erro fora do domínio.

### `shared/`

Contém configuração de runtime e paths do projeto. Não é lugar para regra de
negócio. Se uma função precisa saber *o que* um campo significa, ela pertence ao
domínio ou à aplicação; se precisa apenas saber *onde* está uma configuração,
ela pode pertencer aqui.

## Direção das dependências

```text
Airflow / Portal / Scripts
          ↓
     application  ←  infrastructure
          ↓
        domain
```

- `domain` não depende das outras camadas;
- `application` depende de `domain` e de portas;
- `infrastructure` implementa portas e pode importar tipos necessários da
  aplicação/domínio;
- interfaces externas escolhem e injetam os adaptadores concretos.

## Convenções de evolução

1. Coloque uma regra pura no `domain` quando ela puder ser testada sem I/O.
2. Crie ou amplie um caso de uso em `application` antes de adicioná-lo a uma DAG.
3. Isole clientes, SDKs, armazenamento e rede em `infrastructure`.
4. Mantenha módulos pequenos e coesos; ao crescerem, divida por responsabilidade
   de negócio, não por conveniência de importação.
5. Evite referências a construtoras, ABECIP ou outro domínio dentro de regras
   genéricas. A diferença entre domínios deve vir do contrato semântico.

As fachadas em `airflow/helpers/` e `airflow/plugins/` existem apenas para
compatibilidade temporária. Código novo deve importar diretamente de
`document_processing`.

## Testes

Os testes unitários acompanham essa organização em `tests/unit/`. Valide as
alterações com:

```bash
pytest tests/unit
python -m ruff check src/document_processing tests/unit
```

Para a visão arquitetural completa, consulte a
[ADR-0008](../../docs/adr/0008-nucleo-independente-e-airflow-adaptador.md) e a
[arquitetura de orquestração](../../docs/architecture/arquitetura-orquestracao-airflow.md).
