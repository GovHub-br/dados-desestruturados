# Gabaritos por documento

Um arquivo por documento, nomeado pelo `document_id` do pipeline. E o que as
metricas das fases 0 e 3 comparam com a saida da LLM (`scripts/avaliar_assinatura_layout.py`).

Nenhuma chave e nome de campo de um dominio: tudo e indexado pelo path do
requisito do contrato e pelos seletores da observacao.

```json
{
  "document_id": "...", "entidade": "cury", "dominio": "construtoras",
  "contrato": {"tipo_documento": "construtoras", "versao": "1.9.0"},
  "identidade": {"entidade": "Cury", "periodo": "2T26"},
  "artefatos_esperados_por_requisito": {"<path do requisito>": ["tables/table001.json"]},
  "ancoragens": {
    "<path do requisito>": [
      {"seletores": {"empresa": "cury", "papel_periodo": "periodo_referencia"},
       "arquivo_origem": "tables/table001.json",
       "indice_linha": 2, "rotulo_linha": "Número de Unidades",
       "indice_coluna": 1, "cabecalho_coluna": "2T26",
       "valor": 6549.0, "periodo": "2T26", "obrigatorio": true,
       "conferido_e2e": true}
    ]
  },
  "ausencias_esperadas": [{"requisito": "...", "seletores": {...}, "motivo": "..."}],
  "revisao_pendente": ["decisoes de curadoria ainda abertas"]
}
```

- `conferido_e2e`: o valor bate com `atlas-e2e-regressao` (construtoras). Bancos
  foram conferidos contra o gabarito curado de `atlas-fallback-layout-candidato`.
- `ausencias_esperadas`: o documento nao publica o dado; a resposta correta e
  declarar ausencia (Cyrela 2T26: numero de empreendimentos e VGV, nao unidades).
- `revisao_pendente`: decisoes que o contrato ainda nao fixa (segmentacao
  marca x consolidado na MRV, sufixos de periodo na Direcional, identidade do
  manifesto incompleta). O gabarito registra a escolha feita; mudar a decisao e
  mudar o arquivo, nunca o codigo.

Origem: execucao `baseline0` (2026-09-13/14), candidatos validados + auditoria da
resolucao local com os contratos construtoras v1.9.0 e bancos v2.2.0.
