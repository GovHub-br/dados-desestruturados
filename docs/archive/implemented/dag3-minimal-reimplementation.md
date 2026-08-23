# Guia de reimplementação mínima da DAG 3

## Objetivo

Preservar somente as decisões indispensáveis do experimento atual para reconstruir a DAG 3 no futuro sem recuperar toda a complexidade acumulada no diff.

Este documento é uma referência de reimplementação. Ele não significa que o código atual deva ser mantido.

## Arquitetura que deve ser preservada

```text
Falha da DAG 2
-> seleção de artefatos
-> LLM gera Layout Signature candidato
-> valida candidato
-> revalida na DAG 2
-> publica nova versão
```

A matriz de cobertura, normalizações extensas e outras etapas intermediárias não são requisitos desta arquitetura mínima. Só devem voltar se um problema concreto demonstrar sua necessidade.

## 1. Selecionar a última extração ainda não processada

### Comportamento esperado

Quando a DAG 2 for executada sem `manifest_key` ou `manifest_keys` explícitos:

1. listar os `manifesto_execucao.json` produzidos pela DAG 1;
2. agrupar os manifestos por empresa;
3. selecionar somente a extração mais recente de cada empresa;
4. verificar se essa extração já possui resolução completa;
5. processá-la somente quando estiver pendente.

Não deve reprocessar todas as extrações históricas nem escolher uma extração antiga porque a mais recente já terminou.

### Como foi implementado

Na DAG 2, `descobrir_execucoes_para_resolucao` respeitava esta prioridade:

1. `dag_run.conf.manifest_key`;
2. `dag_run.conf.manifest_keys`;
3. descoberta automática pela função `discover_latest_unresolved_extraction_manifests`.

Na descoberta automática:

- os manifestos eram lidos do prefixo de extrações no MinIO;
- `company_slug`, `document_id` e `execution_id` eram obrigatórios;
- o timestamp UTC no formato `YYYYMMDDTHHMMSSZ` era extraído do `execution_id`;
- a ordenação usava `(timestamp, execution_id, manifest_key)` para desempate;
- apenas o manifesto mais recente de cada empresa era avaliado.

### Como definir “resolução completa”

A existência de qualquer arquivo não basta. A implementação verificava `auditoria_resolucao.json` no mesmo `document_id` e `execution_id` e exigia:

- `summary.validation_status == "compativel"`;
- `summary.campos_mapeamento_com_falha == 0`;
- nenhum campo obrigatório com `status_resolucao` diferente de `resolvido`.

Se a auditoria não existir, estiver ilegível ou não cumprir essas condições, a última extração continua pendente.

### Testes mínimos

- duas extrações da mesma empresa: selecionar apenas a mais recente;
- extração mais recente totalmente resolvida: não selecionar nenhuma dessa empresa;
- campo obrigatório não resolvido: manter a extração como pendente;
- `manifest_key` explícito: não executar descoberta automática.

## 2. Criar uma execução própria para cada tentativa da DAG 3

### Problema que precisa ser evitado

O `execution_id` recebido da DAG 2 identifica a extração original da DAG 1. Reutilizá-lo como diretório da DAG 3 faz novas tentativas sobrescreverem seleção, resposta da LLM e candidato anteriores.

### Identidades necessárias

- `source_execution_id`: execução original da extração, usada para linhagem e leitura dos artefatos.
- `fallback_execution_id`: execução atual da DAG 3, usada para persistir os artefatos de fallback.

O nome `execution_id` pode continuar representando a origem por compatibilidade, mas a distinção conceitual deve permanecer explícita.

### Como foi implementado

Na validação do `dag_run.conf` da DAG 3:

1. obter `dag_run.run_id`;
2. normalizar caracteres inadequados para object keys;
3. gerar `fallback_execution_id` com prefixo `dag_valida_e_fallback_llm__` quando necessário;
4. propagar esse ID pelo contexto, revalidação e publicação.

O prefixo dos artefatos passou a usar:

```text
fallback/<dominio>/<empresa>/document_id=<document_id>/execution_id=<fallback_execution_id>/
```

O `execution_id` original continuou sendo usado para localizar manifesto e extração. Para compatibilidade temporária, quando `fallback_execution_id` não existia, o código retornava ao `execution_id` original.

### Testes mínimos

- duas execuções da DAG 3 para a mesma extração geram prefixos diferentes;
- ambas apontam para o mesmo manifesto de origem;
- uma execução nunca sobrescreve artefatos da outra.

## 3. Retry corretivo da resposta da LLM

### Objetivo

Não descartar uma resposta semanticamente aproveitável quando o problema for corrigível, como:

- JSON truncado ou malformado;
- campo obrigatório ausente;
- estrutura rejeitada pelo modelo Pydantic;
- candidato fora de uma regra de domínio claramente explicável.

### Regra de retry

- fazer a chamada inicial;
- permitir no máximo 3 tentativas corretivas;
- total máximo: 4 chamadas para a mesma geração;
- interromper imediatamente quando a resposta passar pela validação;
- após a terceira correção malsucedida, falhar com o último erro preservado.

### Payload da correção

Enviar novamente apenas o contexto necessário, acrescentando:

```json
{
  "correcao_candidato": {
    "tentativa": 1,
    "maximo_tentativas": 3,
    "erro_validacao": "erro exato e compacto",
    "candidato_invalido": {},
    "instrucao": "corrija somente o erro informado e devolva o objeto completo"
  }
}
```

Para JSON inválido, a mensagem deve pedir um objeto JSON completo, sem Markdown ou texto externo.

### O que não deve consumir retry corretivo

Falhas de autenticação, configuração, modelo inexistente ou outros erros permanentes não devem ser enviados à LLM como se fossem defeitos do candidato.

Erros transitórios de transporte podem ter retry separado e curto, limitado a casos como timeout, HTTP 429, 502, 503 e 504. Esse retry não deve compartilhar o contador das três correções semânticas.

### Testes mínimos

- JSON inválido seguido de JSON válido: sucesso na primeira correção;
- candidato inválido seguido de candidato corrigido: sucesso;
- quatro respostas inválidas: falha após 3 correções;
- timeout ou erro de autenticação: não consumir retry semântico.

## 4. Observabilidade mínima das chamadas LLM

Persistir por etapa, antes e depois da chamada:

- entrada efetivamente enviada: prompt de sistema, `user_payload`, schema esperado, provider e modelo;
- resposta bruta antes do parse;
- resposta validada, quando existir;
- erro de parse ou validação, quando ocorrer;
- número da tentativa.

Em respostas inválidas, o conteúdo bruto deve ser carregado junto ao erro para não desaparecer no stack trace.

Para retries, usar nomes com `_tentativa_N` ou um artefato estruturado que preserve todas as tentativas. Nunca sobrescrever a evidência da tentativa anterior.

Metadados operacionais podem ser persistidos para debug, mas não devem ser enviados à LLM quando não ajudam a tarefa. Cada etapa deve ter um payload próprio e mínimo.

## 5. Gates indispensáveis do candidato

Antes de revalidar na DAG 2:

- parsear a resposta como objeto JSON;
- validar o contrato mínimo com Pydantic;
- rejeitar caminhos selecionados que não existam no `inventory.json`;
- impedir alteração do contrato semântico, regras de governança e versão final;
- impedir escrita direta no layout ativo;
- persistir o resultado como Layout Signature candidato isolado.

Não é necessário recriar de início uma árvore extensa de modelos para cada variação de seletor. Começar com o menor schema que bloqueie alterações perigosas e ampliá-lo apenas com falhas reais observadas.

## 6. Revalidação e publicação segura

A LLM nunca publica diretamente.

1. persistir o candidato em área de fallback;
2. disparar a DAG 2 com `manifest_key` original e override do candidato;
3. impedir que essa revalidação dispare outro fallback recursivo;
4. aceitar somente resultado determinístico compatível;
5. publicar como nova versão;
6. atualizar `current.json` somente depois de toda a publicação concluir;
7. nunca sobrescrever uma versão existente.

No mínimo, a aprovação deve confirmar que não há campos obrigatórios não resolvidos e que o schema resolvido contém os dados críticos esperados.

## 7. O que deve permanecer simples

Na primeira reconstrução, manter apenas duas chamadas de negócio:

1. seleção de caminhos do `inventory.json`;
2. geração do Layout Signature candidato usando os artefatos selecionados.

Não reintroduzir inicialmente:

- matriz de cobertura como chamada LLM separada;
- normalizações genéricas para muitos formatos inventados pela LLM;
- duplicação da mesma regra no prompt, Pydantic e validação de domínio;
- promoção de vários artefatos auxiliares sem necessidade comprovada;
- contexto operacional inteiro dentro do prompt;
- refatorações amplas da DAG 2 que não sejam necessárias para revalidar o candidato.

## 8. Ordem recomendada de reconstrução

1. descoberta da última extração pendente;
2. gatilho da DAG 3 somente quando a DAG 2 exigir fallback;
3. `fallback_execution_id` próprio;
4. seleção de artefatos com payload mínimo;
5. geração e validação mínima do candidato;
6. retry corretivo máximo de 3;
7. persistência de entradas, respostas brutas e erros;
8. revalidação pela DAG 2;
9. publicação versionada sem sobrescrita;
10. somente depois, adicionar novos gates motivados por falhas observadas.

## Critério de controle de escopo

Uma nova função, modelo ou etapa só deve ser adicionada se responder claramente:

1. qual falha real ela evita;
2. por que o gate existente não resolve;
3. qual teste prova sua necessidade;
4. se pertence à seleção, geração, validação, revalidação ou publicação.

Se essas respostas não estiverem claras, a mudança deve ficar fora da implementação mínima.
