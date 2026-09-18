"""Gate de publicacao: compativel nao basta quando um obrigatorio ficou sem valor.

Nao mexe em regras de deteccao de mudanca: um layout recem-criado nao declara
nenhuma, entao "compativel" so diz que nada rodou. A auditoria da revalidacao e
a evidencia usada para decidir se o candidato pode virar layout vigente.
"""

from __future__ import annotations

import pytest

from document_processing.application.use_cases.fallback.candidate_lifecycle import (
    CandidateLifecycleMixin,
)


class _Minio:
    def __init__(self, objects: dict) -> None:
        self.objects = dict(objects)
        self.written: dict = {}

    def get_json(self, *, object_key: str):
        if object_key not in self.objects:
            raise FileNotFoundError(object_key)
        return self.objects[object_key]

    def put_json(self, *, object_key: str, payload: dict) -> str:
        self.written[object_key] = payload
        return f"minio://bucket/{object_key}"


class _Service(CandidateLifecycleMixin):
    def __init__(self, objects: dict) -> None:
        self.minio_client = _Minio(objects)

    def _load_json_object(self, object_key: str, artifact_name: str):
        return self.minio_client.get_json(object_key=object_key)


PREFIX = "fallback/dom/ent/document_id=d/execution_id=e/revalidation"
VALIDACAO = {"status_compatibilidade": {"status": "compativel", "codigos_alerta": []}}
CONF = {"fallback_revalidation_prefix": PREFIX, "candidate_layout_object_key": "cand.json"}


def _auditoria(*itens):
    return {"auditoria_resolucao": list(itens)}


def test_obrigatorio_nao_resolvido_bloqueia_a_publicacao():
    service = _Service(
        {
            f"{PREFIX}/validacao_layout_signature.json": VALIDACAO,
            f"{PREFIX}/auditoria_resolucao.json": _auditoria(
                {"campo_saida": "a.valor", "obrigatorio": True, "status_resolucao": "resolvido"},
                {"campo_saida": "b.valor", "obrigatorio": True, "status_resolucao": "nao_resolvido"},
                {"campo_saida": "c.valor", "obrigatorio": False, "status_resolucao": "nao_resolvido"},
            ),
        }
    )
    with pytest.raises(RuntimeError, match="b.valor"):
        service.evaluate_revalidation_result(CONF)
    resultado = service.minio_client.written[f"{PREFIX}/resultado_revalidacao_candidato.json"]
    assert resultado["aprovado_para_publicacao"] is False
    assert resultado["obrigatorios_nao_resolvidos"] == ["b.valor"]
    assert "OBRIGATORIOS_NAO_RESOLVIDOS_NA_REVALIDACAO" in resultado["codigos_alerta"]


def test_todos_os_obrigatorios_resolvidos_aprova():
    service = _Service(
        {
            f"{PREFIX}/validacao_layout_signature.json": VALIDACAO,
            f"{PREFIX}/auditoria_resolucao.json": _auditoria(
                {"campo_saida": "a.valor", "obrigatorio": True, "status_resolucao": "resolvido"},
                {"campo_saida": "c.valor", "obrigatorio": False, "status_resolucao": "nao_resolvido"},
            ),
        }
    )
    resultado = service.evaluate_revalidation_result(CONF)
    assert resultado["aprovado_para_publicacao"] is True
    assert resultado["obrigatorios_nao_resolvidos"] == []


def test_auditoria_ausente_vira_alerta_e_nao_bloqueia():
    service = _Service({f"{PREFIX}/validacao_layout_signature.json": VALIDACAO})
    resultado = service.evaluate_revalidation_result(CONF)
    assert resultado["aprovado_para_publicacao"] is True
    assert "AUDITORIA_REVALIDACAO_AUSENTE" in resultado["codigos_alerta"]
