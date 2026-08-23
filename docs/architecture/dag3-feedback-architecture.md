# Arquitetura das DAGs e realimentação do fallback

## Resposta curta

O projeto não viola a definição de DAG do Airflow. Cada DAG possui um grafo interno acíclico de tasks. O que existe é uma realimentação controlada entre execuções de DAGs diferentes.

```text
DAG 2: resolução ── falha de layout ──> DAG 3: fallback LLM
                                            │
                                            └── candidato ──> DAG 2: revalidação
```

Isso parece um ciclo no processo de negócio, mas não é um ciclo de dependências entre tasks dentro de uma mesma DAG. O Airflow agenda cada `DagRun` de forma independente.

O requisito arquitetural é garantir que o retorno à DAG 2 seja uma revalidação terminal, e não uma tentativa capaz de disparar a DAG 3 indefinidamente. O código atual já contém essa proteção.

## Fluxo implementado

```text
PDF no MinIO
  │
  ├── DAG de extração Docling → manifesto + tabelas + blocos + inventário
  │
  └── DAG 2 — dag_resolve_schema_saida
        ├── contrato semântico + layout signature
        ├── schema_saida_resolvido + auditoria + validação
        ├── aprovado → encerra
        └── falha de layout → DAG 3 — dag_valida_e_fallback_llm
                                  ├── carrega evidências e chama a LLM
                                  ├── persiste layout candidato
                                  └── dispara DAG 2 em modo de revalidação
                                        ├── aprovado → publica layout
                                        └── reprovado → encerra
```

O encadeamento máximo é `DAG 2 normal → DAG 3 → DAG 2 de revalidação → fim`.

## Por que é acíclico no Airflow

Uma DAG exige que não exista, dentro da sua própria definição, caminho de uma task de volta para ela mesma. Nas DAGs atuais, as dependências internas são lineares:

```text
DAG 2: início → runtime → manifests → resolução → filtro → trigger → fim
DAG 3: início → contexto → LLM → candidato → revalidação → publicação → fim
```

O trigger da DAG 3 cria uma nova instância da DAG 2; ele não conecta uma task da primeira execução à sua própria task anterior. Portanto, o scheduler não recebe uma dependência circular para resolver.

No domínio há um laço de correção, como gerar código, testá-lo e corrigir uma tentativa. O desenho é válido desde que tenha condição explícita de parada.

## Proteções existentes

| Proteção | Implementação atual | Risco evitado |
| --- | --- | --- |
| Revalidação terminal | A DAG 2 identifica `modo_execucao=revalidacao_layout_candidato` e não dispara a DAG 3. | Loop infinito DAG 2 → DAG 3 → DAG 2. |
| Revalidação antes da publicação | A DAG 3 só publica após a DAG 2 aprovar o candidato. | Layout inválido em produção. |
| Espera pela revalidação | O trigger da DAG 3 usa `wait_for_completion=True`. | Publicação sem conhecer o resultado. |
| Estados permitidos | A revalidação precisa encerrar em `success`. | Continuação após falha da DAG 2. |
| Concorrência do fallback | A DAG 3 usa `max_active_runs=1`. | Muitos candidatos concorrentes. |
| ID próprio do fallback | O `fallback_execution_id` é derivado do `run_id` da DAG 3. | Sobrescrever evidências anteriores. |

## Riscos que ainda existem

### Observabilidade distribuída

Uma execução de negócio atravessa pelo menos dois `DagRun`s. O Airflow mostra tasks de cada DAG, enquanto o MinIO correlaciona o caso concreto por `document_id`, `execution_id`, `fallback_execution_id` e manifestos. O OpenMetadata mostra a linhagem lógica das DAGs e seus status, não cada objeto de cada execução.

### Concorrência e duplicidade

Uma revalidação e uma execução manual da DAG 2 podem processar o mesmo documento. A publicação condicionada à aprovação protege a qualidade, mas não impede integralmente duas tentativas equivalentes.

### Falha após aprovação

Se a revalidação terminar com sucesso e a publicação falhar, haverá um candidato aprovado no MinIO que ainda não virou layout publicado. A evidência permanece auditável, mas a retomada precisa ser explícita.

### Repetição de tentativas de negócio

Retries técnicos de HTTP/task não são uma nova tentativa semântica. Porém, várias execuções manuais da DAG 2 podem gerar múltiplos fallbacks se não houver controle de estado por documento.

## Avaliação da arquitetura atual

Para o estágio atual, a separação das DAGs é adequada:

- a resolução determinística permanece isolada da LLM;
- a DAG 2 pode ser testada sem dependência de modelo;
- o fallback e seus artefatos permanecem auditáveis e separados;
- publicar continua sendo consequência de validação determinística;
- contrato e layout são entradas versionadas, preservando o uso para PDFs de qualquer domínio.

Eu manteria esse desenho na primeira versão de produção, mas acrescentaria uma máquina de estados operacional antes de elevar a concorrência.

## Melhorias propostas

### Prioridade alta: estado explícito por documento e contrato

Persistir um registro de controle no MinIO ou em banco operacional, com chave lógica semelhante a:

```text
domain + entity_slug + document_id + contrato_semantico_uri
```

Estados sugeridos:

```text
ORIGEM_PENDENTE → EXTRAIDO → RESOLUCAO_EM_ANDAMENTO → RESOLVIDO
                                  └→ FALLBACK_EM_ANDAMENTO
                                     → CANDIDATO_EM_REVALIDACAO
                                     → LAYOUT_PUBLICADO | FALHA_FINAL
```

Cada transição deve registrar `run_id`, horário, versões usadas e erro resumido. Antes de disparar a DAG 3, a DAG 2 consulta esse estado e evita um fallback duplicado. Isso é genérico para qualquer PDF ou domínio.

### Prioridade alta: formalizar o payload de revalidação

O `modo_execucao` atual funciona, mas o contrato entre as DAGs pode ficar mais claro:

```json
{
  "execution_mode": "candidate_revalidation",
  "source_execution_id": "...",
  "fallback_execution_id": "...",
  "candidate_layout_object_key": "..."
}
```

A regra geral deve ser: revalidar candidato nunca cria outro candidato automaticamente.

### Prioridade média: idempotência da publicação

Calcular um hash do layout candidato normalizado. Se o mesmo hash já foi publicado para o mesmo domínio e contrato, retornar a versão existente em vez de criar uma versão duplicada.

### Prioridade média: eventos em vez de triggers diretos

No futuro, a DAG 2 pode publicar `layout_resolution_failed` e a DAG 3 pode consumi-lo; depois, publicar `layout_candidate_validated`. Isso reduz acoplamento e escala melhor, mas adiciona infraestrutura. Não é necessário no MVP.

### Alternativa: uma DAG orquestradora única

Uma DAG de alto nível poderia coordenar extração, resolução, fallback, revalidação e publicação em um único `DagRun`. Isso melhora a visualização de uma execução, mas acopla etapas hoje independentes. Não é a recomendação atual: a máquina de estados entrega maior benefício com menos mudança.

## Decisão recomendada

1. Manter DAG 2 e DAG 3 separadas.
2. Manter obrigatoriamente a trava da revalidação terminal.
3. Implementar estado operacional por documento/contrato antes de crescer o volume ou permitir muitas execuções simultâneas.
4. Evoluir o OpenMetadata para relacionar manifestos individuais a cada execução se rastreabilidade por PDF se tornar requisito de produto.
5. Avaliar mensageria/eventos apenas quando o volume ou múltiplos consumidores justificarem a infraestrutura adicional.

Com esses limites, a realimentação não é um ciclo problemático: é um fluxo de correção limitado, auditável e seguro.
