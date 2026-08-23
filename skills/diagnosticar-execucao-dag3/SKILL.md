---
name: diagnosticar-execucao-dag3
description: Diagnostica execuções da DAG 3 (`dag_valida_e_fallback_llm`) a partir de logs do Airflow e artefatos persistidos no MinIO/local. Use ao investigar seleção de artefatos, chamadas LLM, consumo de tokens/reasoning, validação de candidatos, revalidação ou publicação, antes de propor a menor correção eficaz.
---

# Diagnosticar execução DAG 3

## Visão geral

Investigue uma execução de ponta a ponta sem adivinhar a causa. Trate os artefatos persistidos como evidência e diferencie falha de transporte, resposta da LLM, validação determinística e revalidação da DAG 2.

## Princípios

- Comece pelo estado terminal no Airflow; o último JSON gerado não prova sucesso.
- Preserve validações: não recomende relaxá-las sem mostrar qual evidência válida foi rejeitada e por quê.
- Prefira uma alteração pequena, genérica para qualquer PDF e verificável por teste ou nova execução. Não altere código, MinIO ou layouts sem pedido explícito.
- Nunca exponha chaves, senhas ou conteúdo sensível de `.env` no relatório.

## Procedimento de investigação

### 1. Localize e delimite a execução

1. Confirme a pasta indicada e liste os arquivos em ordem temporal/nome.
2. Registre `document_id`, `execution_id`, domínio, contrato, modo de fallback e a presença ou ausência de `layout_signature_candidato.json` e `revalidation/`.
3. Consulte a execução da `dag_valida_e_fallback_llm` no Airflow. Anote a task terminal, seu estado e a última exceção. Uma task `skipped` após tentativas internas ainda pode significar falha do candidato.

### 2. Verifique a seleção de artefatos

Abra, nesta ordem:

- `entrada_llm_selecao_artefatos*.json`;
- `resposta_llm_selecao_artefatos*.json`;
- `erro_llm_selecao_artefatos*.json`;
- `selecao_artefatos_layout.json`.

Classifique o resultado:

- erro de API/rede ou JSON inválido: examine `finish_reason`, `usage` e o envelope;
- resposta aceita pela API, mas rejeitada: compare cada âncora declarada com o artefato completo, não só uma amostra;
- seleção validada: use somente seus caminhos como contexto da próxima etapa.

Não confunda uma âncora com redação ligeiramente diferente com falta de dado; localize a linha/cabeçalho real antes de recomendar mudança de prompt ou regra.

### 3. Verifique a geração do candidato

Abra, nesta ordem:

- `entrada_llm_layout_signature_candidato*.json`;
- `erro_llm_layout_signature_candidato*.json`;
- `resposta_llm_layout_signature_candidato*.json`;
- o log de `gerar_layout_candidato_llm` no Airflow.

Para cada tentativa, registre tamanho aproximado do prompt/artefatos, `finish_reason`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, caracteres de `content` e `reasoning_content`, e se a resposta passa JSON, Pydantic e as regras determinísticas.

Interpretação:

- `finish_reason=length` com `content` vazio e reasoning alto: o orçamento de saída foi consumido antes da resposta. É limite de geração, não ausência de evidência por si só.
- JSON inválido/truncado: compare tamanho e fechamento; retries podem ampliar o contexto ao anexar erro/resposta anterior.
- JSON válido rejeitado: cite literalmente a validação e a chave/valor que a causou. Inspecione a gramática de paths, campos fixos, arrays, origem aceita e cobertura exigida antes de culpar a LLM.

### 4. Valide a semântica contra a evidência

Para cada mapeamento recusado ou suspeito:

1. abra o contrato e o campo em `campos_obrigatorios`;
2. abra o arquivo de extração referenciado;
3. confira índices/linhas/cabeçalhos e todos os seletores de arrays;
4. confirme que a sintaxe do path é aceita pelo parser atual;
5. se houver layout candidato, avalie se o mapeamento representa o dado correto, independentemente de ele ter sido formalmente rejeitado.

### 5. Inspecione revalidação e publicação, quando existirem

Se o candidato foi persistido, abra `revalidation/schema_saida_resolvido.json`, `revalidation/auditoria_resolucao.json`, `revalidation/validacao_layout_signature.json`, `revalidation/resultado_revalidacao.json` (se houver) e os logs das tasks posteriores.

Separe claramente: layout aprovado, campos efetivamente resolvidos, regra de detecção compatível e publicação final. Um layout candidato não é um resultado.

## Saída obrigatória do diagnóstico

Entregue um relatório breve, evidenciado e nesta ordem:

1. **Resumo:** execução, estado terminal e etapa que a interrompeu.
2. **Linha do tempo:** seleção → geração/retries → validação → revalidação.
3. **Causa raiz:** exceção literal e arquivos que a comprovam.
4. **O que funcionou:** respostas, seleções ou mapeamentos aproveitáveis.
5. **Custo LLM:** somente quando disponível, incluindo reasoning versus conteúdo.
6. **Correção mínima recomendada:** uma mudança genérica, sua justificativa e teste de confirmação. Separe melhorias opcionais de causa raiz.

## Comandos de apoio

Use `rg --files <pasta>` para inventariar. Para JSON, use `jq` ou leitura estruturada e extraia apenas os campos relevantes. Para o estado definitivo, consulte a API/logs do Airflow; se necessário, use o container do portal para obter token de acesso e consultar `dagRuns` e `taskInstances`.

Ao analisar resposta de API, persista/compare somente o envelope sanitizado; nunca peça ou imprima segredos de configuração.
