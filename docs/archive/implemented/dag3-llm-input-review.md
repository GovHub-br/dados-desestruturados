# Revisão dos inputs enviados à LLM na DAG 3

## Objetivo

Revisar, de baixo para cima, o conteúdo enviado em cada chamada da DAG 3 e retirar do prompt tudo que não contribui diretamente para a decisão da LLM.

Os metadados operacionais continuam podendo ser persistidos no MinIO para rastreabilidade e depuração. Isso não significa que eles devam fazer parte do `user_payload` enviado ao modelo.

## Princípio adotado

Cada etapa deve receber somente o contexto necessário para cumprir sua responsabilidade.

Na etapa `selecao_artefatos`, a responsabilidade da LLM é identificar, a partir do `inventory.json`, quais caminhos devem ser consultados nas etapas seguintes para encontrar evidências dos campos-alvo.

## Etapa: seleção de artefatos

### Chaves avaliadas — bloco final

| Chave | Decisão | Justificativa |
|---|---|---|
| `manifesto_extracao_ref.artifact_uris_count` | Remover do prompt | É uma contagem operacional. O próprio inventário já apresenta os artefatos disponíveis e seus caminhos. |
| `modo_criacao_inicial_layout` | Remover do prompt desta etapa | Controla o fluxo da DAG, mas não ajuda a identificar quais caminhos contêm os dados importantes. Pode continuar no contexto interno. |
| `status` | Remover do prompt | É estado interno do processo e não influencia a seleção de caminhos. |
| `tipo_artefato` | Remover do prompt | É metadado de classificação e rastreabilidade, sem utilidade para a decisão da LLM. |

### Destino das chaves removidas

As chaves podem continuar presentes no artefato operacional completo persistido no MinIO. Devem apenas ser excluídas do `user_payload` da chamada de seleção.

### Conteúdo que deve permanecer nessa etapa

- campos-alvo que precisam ser localizados;
- itens e caminhos disponíveis no `inventory.json`;
- informações do inventário que descrevam o conteúdo provável de cada caminho;
- regras e limites da seleção;
- contexto semântico mínimo necessário para relacionar campos-alvo e artefatos.

## Mudanças pendentes de implementação

- Montar um payload específico para `selecao_artefatos`, em vez de encaminhar quase todo o `fallback_problem_context`.
- Remover desse payload as quatro chaves avaliadas acima.
- Preservar o contexto operacional completo no MinIO para depuração.
- Adicionar teste garantindo que metadados operacionais não sejam enviados à LLM nessa etapa.

## Próximas avaliações

Continuar a revisão das demais chaves de `entrada_llm_selecao_artefatos.json`. Nenhuma mudança de código deste documento deve ser aplicada antes de concluir a avaliação do payload da etapa.
