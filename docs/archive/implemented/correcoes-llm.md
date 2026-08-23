# Plano detalhado de correção das DAGs 2 e 3

## Status de implementação

Implementado em 2026-07-02 no fluxo experimental das DAGs 2 e 3:

- contratos Pydantic discriminados e estritos;
- criação inicial com contrato completo e campos-alvo concretos;
- seleção de artefatos, matriz de cobertura e geração do candidato;
- reparo da matriz e do candidato com evidências preservadas;
- bloqueio de regras vazias, schema vazio e mappings obrigatórios não resolvidos;
- gate rigoroso de publicação e promoção para a resolução oficial;
- reconstrução determinística do envelope governado do layout.
- compatibilidade com Ollama que rejeita schemas discriminados: repetição com
  `format=json`, sem remover a validação Pydantic local;
- logs explícitos após seleção de artefatos e aprovação da matriz.

Os valores conhecidos da Cury 1T26 são critérios exclusivos da fixture E2E e
não são hardcoded no comportamento genérico.

### Resultado do E2E de 2026-07-02

A execução comprovou o fluxo de três passes, a revalidação e a promoção, mas
também revelou um falso positivo adicional: a LLM tentou gravar os valores
8.001 e 7.786 como `valor_fixo`. O schema resultante criou itens de período com
`valor`, `periodo` e `escopo_periodo` nulos.

O gate foi corrigido depois dessa descoberta para:

- proibir `valor_fixo` em paths `valores[papel_periodo=...]`;
- exigir `celula_de_tabela` para valores operacionais dinâmicos;
- exigir o mapping do período correspondente quando um valor for localizado;
- considerar dados críticos apenas itens com `valor`, `periodo` e
  `escopo_periodo` materializados;
- classificar essa falha como remapeamento total, em vez de compatibilidade.

A versão `v1.1.0` gerada nesse ensaio deve ser tratada como rejeitada e não como
referência funcional, apesar de ter sido preservada para auditoria.

**Arquivo sugerido:** `resultados_contrutoras/documentacao/PLANO_CORRECAO_LAYOUT_SIGNATURE_LLM.md`

## 1. Objetivo

Corrigir o fluxo de criação, validação, revalidação e publicação de Layout Signatures gerados por LLM.

O processo deverá garantir que:

- a DAG 2 só produza artefatos de resolução quando houver uma assinatura para validar;
- a LLM receba contrato e evidências suficientes;
- o layout candidato cubra integralmente o contrato semântico;
- mappings, fontes, regras e seletores sejam estruturalmente válidos;
- a DAG 2 valide regras e efetivamente resolva o schema;
- nenhuma validação vazia seja considerada compatível;
- nenhum layout seja publicado com schema vazio;
- os resultados aprovados sejam promovidos para o prefixo oficial de resolução.

O layout manual da Cury será utilizado apenas como referência interna para comparação. Ele não será enviado à LLM e não será transformado em template para outras empresas.

---

## 2. Diagnóstico do resultado atual

### 2.1 Comparação quantitativa

| Componente | Layout manual | Layout LLM |
|---|---:|---:|
| Campos estruturais na raiz | 10 | 7 |
| Fontes relevantes | 5 | 0 |
| Regras determinísticas | 10 | 0 |
| Mappings canônicos | 32 | 1 |
| Mappings resolvidos | 32 esperados | 0 |
| Período de referência | `1T26` | `null` |

### 2.2 Tipos de mapping do layout manual

- 16 mappings `valor_fixo`;
- 10 mappings `celula_de_tabela`;
- 5 mappings `cabecalho_de_tabela`;
- 1 mapping `campo_derivado`.

### 2.3 Defeitos do layout da LLM

O layout publicado contém apenas o mapping externo:

```text
balancos_das_empresas.titulo
```

Dentro dele foram aninhados incorretamente outros mappings:

```text
fonte
periodo_referencia
balancos_das_empresas.lancamentos.dados
balancos_das_empresas.lancamentos.dados.valores
balancos_das_empresas.vendas.dados
balancos_das_empresas.vendas.dados.valores
```

Também foi aceita a chave sintaticamente corrompida:

```text
obrigatorio":true},
```

O layout ainda foi publicado sem:

- `tipo_artefato`;
- `empresa`;
- `tipo_documento`;
- `documento_origem`;
- `referencia_contrato_semantico`;
- `regras_execucao`;
- fontes relevantes;
- regras de detecção;
- mappings suficientes.

---



## 4. Disponibilizar o contrato completo para a criação inicial

### Problema

O contexto atual reduz o `schema_saida` com profundidade máxima 2. Isso oculta a estrutura completa de:

- `dados[]`;
- `valores[]`;
- lançamentos;
- vendas;
- campos internos dos itens;
- papéis de período.

### Alteração

Para `criacao_inicial_layout`, o contexto deverá incluir:

- `schema_saida` completo;
- todos os paths navegáveis;
- todos os arrays;
- tipos esperados;
- nulabilidade;
- entidades;
- métricas;
- sinônimos;
- papéis de período;
- empresa obtida do manifesto;
- tipo documental;
- período identificado.

A redução por profundidade continuará disponível apenas para correções parciais focadas.

### Campos-alvo concretos

O código deverá transformar os paths genéricos do contrato em uma lista de campos-alvo concretos para aquela execução.

Exemplos:

```text
balancos_das_empresas.lancamentos.dados[empresa=Cury].empresa
balancos_das_empresas.lancamentos.dados[empresa=Cury].valores[papel_periodo=periodo_referencia]
balancos_das_empresas.vendas.dados[empresa=Cury].valores[papel_periodo=periodo_12m_atual]
```

Essa lista orienta a LLM, mas não fornece os mappings prontos.

---

## 5. Implementar geração LLM em três passes

## 5.1 Passo 1: seleção de artefatos

A primeira chamada continuará selecionando artefatos a partir do `inventory.json`.

Para criação inicial, a seleção deverá cobrir obrigatoriamente:

- tabela de lançamentos;
- tabela de vendas;
- metadados das tabelas;
- células ou linhas normalizadas;
- seções;
- blocos textuais quando necessários;
- manifesto e metadata da extração.

### Novo gate de seleção

A seleção será rejeitada se não houver evidência para:

- lançamentos;
- vendas;
- empresa;
- período de referência;
- períodos comparativos;
- linha do indicador esperado.

### Artefato persistido

```text
fallback/.../selecao_artefatos_layout.json
```

Deverá conter:

- paths selecionados;
- motivo por path;
- campos do contrato cobertos;
- grupos sem evidência;
- resposta bruta da LLM;
- validação da seleção.

---

## 5.2 Passo 2: matriz de cobertura

Adicionar uma chamada intermediária para gerar:

```text
fallback/.../matriz_cobertura_layout.json
```

### Estrutura proposta

```json
{
  "tipo_artefato": "matriz_cobertura_layout",
  "document_id": "...",
  "execution_id_origem": "...",
  "campos": [
    {
      "campo_saida": "periodo_referencia",
      "status": "localizado",
      "tipo_origem_proposto": "cabecalho_de_tabela",
      "arquivo_origem": "tables/table001.json",
      "evidencia": {
        "valor_observado": "1T26",
        "indice_coluna": 1
      },
      "obrigatorio": true
    }
  ],
  "resumo": {
    "campos_esperados": 32,
    "campos_localizados": 32,
    "campos_nao_localizados": 0,
    "cobertura_percentual": 100
  }
}
```

### Regras

- Cada campo-alvo concreto deverá aparecer exatamente uma vez.
- Campos obrigatórios não podem ficar ausentes.
- Um campo não poderá declarar artefato fora do inventário.
- Evidências deverão existir no conteúdo carregado.
- A matriz não poderá conter valores finais de negócio como produto resolvido.
- A matriz servirá como plano de construção do layout, não como `schema_saida_resolvido`.

### Gate

A geração do layout final será bloqueada quando:

- cobertura obrigatória for menor que 100%;
- houver campos duplicados;
- algum artefato não existir;
- um array não tiver seletor explícito;
- lançamentos ou vendas não tiverem evidência;
- os papéis de período não puderem ser identificados.

---

## 5.3 Passo 3: geração do layout completo

A terceira chamada receberá:

- contrato completo;
- campos-alvo concretos;
- matriz validada;
- artefatos selecionados;
- evidências estruturais;
- restrições de governança;
- schema JSON completo dos modelos Pydantic.

A resposta deverá conter:

- fontes relevantes;
- regras determinísticas;
- mappings canônicos;
- metadados estruturais de evidência;
- lineage de candidato;
- escopo da correção.

Somente depois da matriz aprovada, a LLM gera:
{
  "fontes_relevantes": {...},
  "regras_deteccao_mudanca": [...],
  "mapeamento_canonico": {...},
  "metadados_estruturais_evidencia": {...}
}
O validador compara o resultado final com a matriz:
campos da matriz = chaves externas de mapeamento_canonico
Isso teria detectado imediatamente o problema atual:
esperados: 32
gerados corretamente: 1
aninhados incorretamente: 7
faltantes: 31
A principal vantagem da matriz é transformar “gere um layout completo” em uma obrigação verificável campo a campo. Ela também permite reparos focados, sem pedir à LLM que regenere cegamente um JSON enorme.

### Regra de completude

O conjunto de mappings externos deverá ser igual ao conjunto de campos aprovados na matriz.

Mappings não poderão ser colocados dentro de outro mapping.

---

## 6. Substituir o modelo genérico de mapping

### Problema

`CanonicalMappingEntry` declara somente:

```text
tipo_origem
arquivo_origem
obrigatorio
```

Além disso, usa `extra="allow"`.

### Alteração

Criar modelos discriminados pelo campo `tipo_origem`.

### `ValorFixoMapping`

Campos:

- `tipo_origem = valor_fixo`;
- `valor_fixo`;
- `obrigatorio`.

Não aceita:

- arquivo;
- seletor de linha;
- seletor de coluna.

### `CampoDerivadoMapping`

Campos:

- `tipo_origem = campo_derivado`;
- `campo_origem`;
- `obrigatorio`.

O campo de origem deverá existir no conjunto de mappings.

### `BlocoTextualMapping`

Campos:

- `tipo_origem = bloco_textual`;
- `arquivo_origem`;
- seletor textual suportado pelo resolvedor;
- padrão ou valor aceito;
- escopo de seção;
- `obrigatorio`.

### `CabecalhoTabelaMapping`

Campos:

- `tipo_origem = cabecalho_de_tabela`;
- `arquivo_origem`;
- `arquivo_metadados`;
- `seletor_coluna`;
- `papel_periodo`;
- `page_number`;
- `section_id`;
- `obrigatorio`.

### `CelulaTabelaMapping`

Campos:

- `tipo_origem = celula_de_tabela`;
- `arquivo_origem`;
- `arquivo_metadados`;
- `seletor_linha`;
- `seletor_coluna`;
- `papel_periodo`;
- `escopo_periodo`;
- `normalizacao`;
- evidências estruturais opcionais;
- `obrigatorio`.

### Configuração

Todos deverão usar:

```python
ConfigDict(extra="forbid")
```

O JSON Schema discriminado será enviado ao provedor LLM.

---

## 7. Modelar seletores e regras explicitamente

Criar modelos Pydantic para:

- seletor de linha;
- seletor de coluna;
- normalização;
- fonte relevante;
- referência de tabela;
- evidência estrutural;
- regra `arquivo_existe`;
- regra `secao_existe`;
- regra `linha_existe_em_tabela`;
- regra `perfil_colunas_periodo_existe_em_tabela`;
- regra `valor_normalizavel`.

Cada regra deverá ter seus campos obrigatórios definidos conforme `tipo_teste`.

Uma regra sem os parâmetros necessários deverá falhar antes da revalidação.

---

## 8. Melhorar as instruções para a LLM

### Remover exemplos vazios

Não usar como principal exemplo:

```json
{
  "fontes_relevantes": {},
  "regras_deteccao_mudanca": [],
  "mapeamento_canonico": {}
}
```

### Incluir checklist obrigatório

O prompt deverá exigir que a LLM confirme internamente:

- todos os campos da matriz foram mapeados;
- cada mapping é uma chave externa independente;
- todos os arrays têm seletores;
- todos os mappings têm tipo de origem compatível;
- fontes relevantes não estão vazias;
- regras determinísticas não estão vazias;
- lançamentos e vendas possuem fonte e seletor;
- cinco papéis de período foram tratados;
- nenhum percentual derivado foi prometido;
- nenhuma regra de governança foi criada.

### Não incluir o layout manual

O layout manual da Cury não será enviado:

- no system prompt;
- no user payload;
- no schema de resposta;
- no contexto de reparo;
- na seleção de artefatos.

---

## 9. Melhorar o fluxo de reparo

### Problema

O reparo atual recebe o erro e o candidato inválido, mas perde artefatos e evidências.

### Alteração

Toda tentativa de reparo deverá receber:

- erro estruturado;
- candidato anterior;
- matriz de cobertura;
- campos faltantes;
- artefatos relacionados ao erro;
- evidências observadas;
- cobertura anterior;
- regras já aprovadas.

### Categorias de erro

- JSON inválido;
- estrutura inválida;
- campo extra;
- mapping aninhado;
- cobertura incompleta;
- seletor inválido;
- origem inexistente;
- regra incompleta;
- falha de resolução;
- divergência de período.

### Proteções

- Uma correção não poderá reduzir a cobertura anterior.
- Uma correção estrutural não poderá remover mappings válidos.
- Respostas truncadas serão rejeitadas.
- Cada tentativa será persistida separadamente.
- Ao atingir o limite, o candidato ficará como `rejeitado`.

---

## 10. Adicionar validação recursiva do candidato

O validador deverá percorrer toda a árvore do candidato.

Deverá rejeitar:

- paths do contrato encontrados dentro de uma entrada de mapping;
- objetos com `tipo_origem` aninhados em outro mapping;
- mappings duplicados;
- chaves desconhecidas;
- strings que aparentem fragmentos de JSON;
- arrays sem seletores;
- mapping path fora do contrato;
- origem fora do manifesto;
- normalização incompatível;
- campo derivado apontando para campo ausente.

A normalização automática continuará limitada a seções raiz inequivocamente deslocadas.

Mappings aninhados não serão movidos automaticamente; serão rejeitados e enviados para reparo.

---

## 11. Validar cobertura antes da DAG 2

O `FallbackCandidateValidationService` deverá comparar:

```text
campos esperados da matriz
versus
chaves externas de mapeamento_canonico
```

O relatório deverá informar:

```json
{
  "campos_esperados": 32,
  "campos_mapeados": 32,
  "campos_faltantes": [],
  "campos_extras": [],
  "cobertura_percentual": 100
}
```

Para criação inicial, cobertura menor que 100% bloqueia persistência e revalidação.

---

## 12. Fortalecer a validação determinística da DAG 2

### Zero regras

Alterar:

```python
compatible = rejected == 0
```

Para uma decisão que considere:

- existência de regras;
- regras obrigatórias;
- cobertura;
- resolução;
- consistência de períodos.

Zero regras deverá gerar:

```text
FALHA_LAYOUT_SEM_REGRAS
```

### Famílias mínimas de regras

Para cada operação crítica, exigir:

- fonte ou seção;
- arquivo da tabela;
- linha do indicador;
- perfil de colunas de período;
- valor de referência normalizável.

Para lançamentos e vendas, o resultado deverá ser funcionalmente comparável às 10 regras do layout manual.

A quantidade exata não será hardcoded; as famílias serão derivadas dos conceitos críticos.

---

## 13. Validar consistência dos períodos

A DAG 2 deverá resolver independentemente o perfil de períodos de:

- lançamentos;
- vendas.

Depois deverá comparar:

- período de referência;
- período comparativo anterior;
- mesmo período do ano anterior;
- período de 12 meses atual;
- período de 12 meses anterior.

Qualquer divergência deverá produzir incompatibilidade e código de ruptura estrutural ampla.

---

## 14. Integrar resultado da resolução ao status final

A compatibilidade não poderá depender apenas das regras.

A decisão final deverá considerar:

```text
validacao das regras
+
cobertura do mapping
+
resultado da resolução
+
consistência do schema
```

### Bloqueios obrigatórios

- zero mappings resolvidos;
- campo obrigatório não resolvido;
- `periodo_referencia = null`;
- lançamentos vazios;
- vendas vazias;
- schema fora do contrato;
- percentual derivado presente;
- auditoria com falha obrigatória.

---

## 15. Enriquecer os artefatos da DAG 2

### Validação

Adicionar:

```json
{
  "cobertura_mapeamento": {
    "campos_esperados": 32,
    "campos_presentes": 32,
    "campos_resolvidos": 32,
    "campos_faltantes": [],
    "campos_com_falha": [],
    "percentual": 100
  },
  "apto_para_publicacao": true,
  "apto_para_bronze": true
}
```

### Auditoria

Registrar para cada campo:

- mapping path;
- arquivo;
- seletor;
- valor bruto;
- valor normalizado;
- status;
- evidência;
- regra associada.

### Schema resolvido

Garantir:

- somente campos do contrato;
- valores brutos;
- nenhuma variação percentual derivada;
- período e escopo preenchidos;
- lançamentos e vendas materializados.

---

## 16. Corrigir a construção do layout publicado

### Problema

Na criação inicial, `base_layout` é vazio. O publicador copia somente as seções presentes no candidato e não recompõe o envelope.

### Alteração

O publicador deverá construir deterministicamente:

- `tipo_artefato`;
- `empresa`;
- `tipo_documento`;
- `documento_origem`;
- `referencia_contrato_semantico`;
- `regras_execucao`;
- `versao_artefato`;
- `publicado_em`;
- lineage.

### Fontes desses campos

- empresa: manifesto;
- tipo documental: classificação do documento;
- documento de origem: manifesto;
- contrato: contrato carregado;
- regras de governança: configuração do pipeline;
- versão: serviço de versionamento;
- lineage: candidato e artefatos de revalidação.

A LLM continuará responsável pelo conteúdo operacional:

- fontes;
- regras de detecção;
- mappings;
- seletores;
- evidências estruturais.

---

## 17. Criar gate rigoroso de publicação

A publicação automática somente poderá ocorrer quando:

1. candidato Pydantic válido;
2. matriz com 100% de cobertura obrigatória;
3. nenhuma fonte inválida;
4. regras obrigatórias presentes;
5. todas as regras obrigatórias aprovadas;
6. todos os mappings obrigatórios resolvidos;
7. período de referência preenchido;
8. lançamentos materializados;
9. vendas materializadas;
10. auditoria sem falha obrigatória;
11. schema aderente ao contrato;
12. ausência de percentuais derivados;
13. três artefatos de revalidação presentes;
14. lineage consistente;
15. layout final completo validado novamente.

Apenas `status == compativel` não será suficiente.

---

## 18. Promover artefatos aprovados para resolução oficial

A revalidação continuará sendo gravada inicialmente em:

```text
fallback/.../revalidation/
```

Depois da aprovação, promover:

```text
validacao_layout_signature.json
schema_saida_resolvido.json
auditoria_resolucao.json
```

Para:

```text
execucoes/construtoras/resolucao/<empresa>/
  document_id=<document_id>/
  execution_id=<execution_id>/
  resolution/
```

O fallback deverá manter:

- candidato;
- seleção;
- matriz;
- tentativas;
- resultado da revalidação;
- decisão de publicação;
- ponteiros para os artefatos oficiais.

Nenhum artefato histórico será sobrescrito.

---

## 19. Corrigir o estado atual do MinIO

- Preservar `layouts/construtoras/cury/v1.0.0/` como evidência histórica.
- Registrar o layout como rejeitado no fallback.
- Remover `layouts/construtoras/cury/current.json`.
- Não deixar layout ativo para a Cury até nova criação inicial ser aprovada.
- Não apagar extrações, contrato, PDF ou artefatos da DAG 1.

---

## 20. Comparador interno com o layout manual

Criar ferramenta de avaliação que compare:

- campos raiz;
- fontes;
- famílias de regras;
- mapping paths;
- tipos de origem;
- arquivos;
- seletores;
- normalizações;
- papéis de período;
- schema resolvido.

### Métricas

- recall de mapping paths;
- mappings extras;
- cobertura por operação;
- cobertura por período;
- equivalência funcional das regras;
- igualdade do schema resolvido;
- campos resolvidos versus esperados.

O layout manual nunca será usado na geração; apenas na avaliação interna da fixture Cury.

---

## 21. Testes unitários

Adicionar cenários para:

- mapping aninhado;
- chave extra;
- chave corrompida;
- origem inexistente;
- seletor ausente;
- matriz incompleta;
- zero regras;
- zero mappings;
- campo obrigatório não resolvido;
- schema vazio;
- período nulo;
- vendas vazias;
- lançamentos vazios;
- divergência de períodos;
- percentual derivado;
- reparo que reduz cobertura;
- publicação sem envelope;
- publicação sem artefatos oficiais.

---

## 22. Testes de integração

### Criação inicial sem layout

Verificar que:

- DAG 2 não persiste artefatos de resolução sem uma assinatura de layout;
- DAG 3 é acionada;
- `LAYOUT_SIGNATURE_AUSENTE` é transportado no contexto operacional do fallback.

### Candidato incompleto

Verificar que:

- candidato permanece em fallback;
- DAG 2 pode revalidar para diagnóstico;
- publicação é bloqueada;
- `current.json` não é criado.

### Candidato completo

Verificar que:

- revalidação passa;
- mappings são resolvidos;
- artefatos são promovidos;
- nova versão é criada;
- `current.json` é atualizado ao final.

---

## 23. Critérios E2E da Cury

Os valores desta seção pertencem somente ao PDF Cury 1T26 usado como fixture.
Outros documentos devem ser avaliados contra os próprios valores observados e
contra os campos derivados do contrato semântico.

A execução será considerada satisfatória quando:

- contrato vier do MinIO;
- inventário vier da DAG 1;
- LLM selecionar evidências adequadas;
- matriz cobrir todos os campos obrigatórios;
- layout possuir estrutura funcionalmente equivalente ao manual;
- regras críticas forem executadas;
- mappings forem resolvidos;
- `periodo_referencia = 1T26`;
- lançamentos 1T26 = `8.001`;
- vendas 1T26 = `7.786`;
- valores comparativos brutos forem preservados;
- percentuais derivados não forem publicados;
- artefatos oficiais existirem;
- layout versionado for imutável;
- `current.json` apontar apenas para o layout aprovado.

---

## 24. Atualização da documentação

Atualizar:

- `SPEC_PROJETO_CONSTRUTORAS.md`;
- `FLUXO_COMPLETO_DAG3_FALLBACK_LLM.md`;
- `IMPLEMENTACAO_DAG2_RESOLVE_SCHEMA_SAIDA.md`;
- `ARQUITETURA_DAGS_CONSTRUTORAS.md`;
- documentação do modelo de pastas do MinIO.

Documentar:

- geração em três passes;
- matriz de cobertura;
- modelos Pydantic;
- gates de resolução;
- publicação automática rigorosa;
- promoção de artefatos;
- recuperação de layouts rejeitados;
- comparação interna com fixtures manuais.

---

## 25. Ordem recomendada de implementação

1. Adicionar testes que reproduzam o falso positivo atual.
2. Tornar modelos Pydantic estritos.
3. Implementar modelos por tipo de origem e regra.
4. Corrigir contexto completo de criação inicial.
5. Implementar matriz de cobertura.
6. Atualizar prompts.
7. Melhorar reparos.
8. Implementar cobertura recursiva do candidato.
9. Corrigir a validação `0/0`.
10. Integrar resolução ao status final.
11. Corrigir o envelope publicado.
12. Implementar promoção para resolução oficial.
13. Corrigir o estado inválido no MinIO.
14. Executar E2E Cury.
15. Gerar comparativo contra o layout manual.
16. Atualizar documentação.

## Premissas finais

- A LLM gera o conteúdo operacional completo do layout.
- O contrato semântico define os campos que precisam ser localizados.
- O layout manual serve apenas como tabela verdade interna.
- Governança e versionamento não são definidos pela LLM.
- A publicação será automática apenas após todos os gates.
- Nenhuma resposta da LLM será considerada verdadeira sem revalidação determinística.
