from __future__ import annotations

from typing import Any

from ..clients import LlmClientError, build_llm_client
from ..config import RuntimeConfig
from ..helpers import stable_id
from ..models import TextExtractionCandidateRecord, TextFactRecord, TextStructureRecord


SYSTEM_PROMPT = """Voce estrutura trechos extraidos de PDFs corporativos em JSON.
Recebera um objeto com section_title, matched_values e context_text.
Seu trabalho e filtrar relevancia antes de extrair: inclua apenas fatos materiais para analise operacional, financeira ou de negocio.
Responda apenas JSON valido, sem markdown.

Fatos relevantes normalmente incluem:
- indicadores financeiros ou operacionais: receita, VGV, vendas, lancamentos, unidades, margem, caixa, landbank, VSO, backlog, preco medio, entregas;
- valores monetarios, percentuais, quantidades, periodos e comparacoes diretamente ligados a esses indicadores;
- eventos materiais com impacto analitico claro, como lancamento, entrega ou backlog, quando houver quantidade, valor financeiro, periodo ou comparacao.

Ignore e nao coloque em facts:
- notas de rodape, criterios metodologicos, legendas e observacoes explicativas sem indicador material;
- numeros que sejam apenas marcadores de nota, chamadas, itens de lista, pagina, identificador, fase, ranking ou contador;
- nomes de empreendimentos, cidades, estados e datas isoladas quando nao houver unidade, VGV, valor financeiro, quantidade, percentual ou comparacao relevante;
- frases institucionais, cabecalhos, sumario, data de publicacao, nome da companhia e texto puramente narrativo;
- definicoes como "inclui", "exclui", "considera somente", "criterio", "fluxo normal" ou "repasses efetivamente realizados", exceto se acompanharem um indicador material no mesmo fato;
- fatos duplicados ou subdivisoes artificiais de um mesmo indicador. Nao crie um fato separado so para a variacao percentual se ela ja puder ficar em comparison do indicador principal.

Regras de saida:
- Extraia somente fatos sustentados literalmente por context_text.
- Nao invente valores, entidades, periodos ou comparacoes ausentes no texto.
- Use metric curto e canonico, como "lancamentos_vgv", "lancamentos_unidades", "vendas_liquidas_vgv", "vendas_liquidas_unidades", "preco_medio", "vso", "backlog_unidades", "landbank_vgv", "geracao_caixa".
- Use value normalizado quando possivel: "856.4" para "R$ 856,4 milhões", "4279" para "4.279 unidades", "85.2" para "85,2%".
- Use unit para moeda, escala, percentual ou unidade fisica: "BRL milhoes", "BRL mil", "unidades", "%", "p.p.".
- Use qualifier para periodo, segmento, empreendimento ou recorte somente quando ajudar a identificar o indicador.
- Use comparison para variacao ou base comparativa, como "+92,9% vs. 1T25".
- raw_text deve ser o menor trecho literal que sustenta o fato.
- entities deve ficar vazio, exceto quando a entidade for indispensavel para interpretar um fato material extraido.
- narrative_summary deve ser null quando facts estiver vazio.
- Se o trecho nao tiver fatos relevantes, responda com context_type null, entities {}, facts [], narrative_summary null e confidence entre 0.0 e 0.2.
- Se houver fatos relevantes misturados com notas ou ruido, ignore o ruido e extraia apenas os fatos relevantes.

Exemplos do que NAO extrair:
- "1 Inclui unidades habitacionais e lotes comerciais." -> facts []
- "2 Exclui o valor atribuido a terrenistas." -> facts []
- "Residencial Tivoli - Fase 1, Sinop - MT | Lancamento: marco/2026" -> facts [] se nao houver unidades, VGV, valor, percentual ou comparacao no mesmo trecho.
- "Sao Paulo, 15 de abril de 2026 - Pacaembu Construtora S.A." -> facts []

Exemplo do que extrair:
- "No 1T26, os lancamentos somaram R$ 856,4 milhoes em VGV (+92,9% vs. 1T25), correspondentes a 4.279 unidades (+85,2% vs. 1T25)."
  -> dois facts: lancamentos_vgv e lancamentos_unidades.

Schema de resposta:
{
  "context_type": "tipo curto e generico do contexto relevante, ou null",
  "entities": {"nome_da_entidade": "valor"},
  "facts": [
    {
      "metric": "nome canonico curto da metrica relevante",
      "value": "valor normalizado quando possivel, ou valor textual",
      "unit": "unidade, moeda ou escala quando clara",
      "qualifier": "periodo, recorte, local, empreendimento ou segmento quando relevante",
      "comparison": "comparacao textual quando clara",
      "raw_text": "trecho literal minimo que sustenta o fato"
    }
  ],
  "narrative_summary": "resumo curto apenas dos fatos relevantes, ou null",
  "confidence": 0.0
}
"""


def _coerce_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, numeric))


def _coerce_facts(value: Any) -> list[TextFactRecord]:
    if not isinstance(value, list):
        return []
    facts: list[TextFactRecord] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        raw_text = item.get("raw_text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue
        facts.append(
            TextFactRecord(
                metric=item.get("metric") if isinstance(item.get("metric"), str) else None,
                value=item.get("value"),
                unit=item.get("unit") if isinstance(item.get("unit"), str) else None,
                qualifier=item.get("qualifier") if isinstance(item.get("qualifier"), str) else None,
                comparison=item.get("comparison") if isinstance(item.get("comparison"), str) else None,
                raw_text=raw_text.strip(),
            )
        )
    return facts


def _build_user_payload(candidate: TextExtractionCandidateRecord) -> dict[str, Any]:
    return {
        "document_id": candidate.document_id,
        "candidate_id": candidate.candidate_id,
        "section_id": candidate.section_id,
        "section_title": candidate.section_title,
        "source_blocks": candidate.source_blocks,
        "matched_values": [match.model_dump(mode="json") for match in candidate.matched_values],
        "context_text": candidate.context_text,
    }


def _record_from_payload(
    *,
    candidate: TextExtractionCandidateRecord,
    payload: dict[str, Any],
    raw_response: str | None,
    error: str | None = None,
) -> TextStructureRecord:
    entities = payload.get("entities")
    if not isinstance(entities, dict):
        entities = {}

    return TextStructureRecord(
        record_id=stable_id(candidate.document_id, "text_structure", candidate.candidate_id),
        document_id=candidate.document_id,
        candidate_id=candidate.candidate_id,
        page_number=candidate.page_number,
        section_id=candidate.section_id,
        section_title=candidate.section_title,
        context_type=payload.get("context_type") if isinstance(payload.get("context_type"), str) else None,
        source_blocks=candidate.source_blocks,
        matched_values=candidate.matched_values,
        entities=entities,
        facts=_coerce_facts(payload.get("facts")),
        narrative_summary=payload.get("narrative_summary") if isinstance(payload.get("narrative_summary"), str) else None,
        confidence=_coerce_confidence(payload.get("confidence")),
        context_text=candidate.context_text,
        raw_response=raw_response,
        error=error,
    )


def _error_record(candidate: TextExtractionCandidateRecord, error: str) -> TextStructureRecord:
    return _record_from_payload(candidate=candidate, payload={}, raw_response=None, error=error)


def _has_relevant_facts(record: TextStructureRecord) -> bool:
    return bool(record.facts)


def extract_text_structures(
    document_id: str,
    candidates: list[TextExtractionCandidateRecord],
    config: RuntimeConfig,
) -> list[TextStructureRecord]:
    del document_id
    client = build_llm_client(config)
    records: list[TextStructureRecord] = []

    for candidate in candidates:
        try:
            payload, raw_response = client.extract_json(
                system_prompt=SYSTEM_PROMPT,
                user_payload=_build_user_payload(candidate),
            )
            record = _record_from_payload(candidate=candidate, payload=payload, raw_response=raw_response)
            if _has_relevant_facts(record):
                records.append(record)
        except LlmClientError as exc:
            if config.llm_fail_fast:
                raise
            record = _error_record(candidate, str(exc))
            if _has_relevant_facts(record):
                records.append(record)

    return records
