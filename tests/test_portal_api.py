"""Cobertura das rotas do portal apos a modularizacao.

O MinIO e o Airflow sao substituidos por dublês: os testes verificam o contrato
HTTP e os artefatos gravados, nao a infraestrutura.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("minio")

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from portal import storage  # noqa: E402
from portal.app import app  # noqa: E402
from portal.services import airflow, tracing  # noqa: E402

CONTRACT = {
    "tipo_documento": "contrato_semantico",
    "versao": "1.8.0",
    "dominio": "construtoras",
    "contrato_semantico": {"descricao": "teste"},
    "schema_saida": {"titulo": "string"},
}


class FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = False):
        for key in sorted(self.objects):
            if key.startswith(prefix):
                yield SimpleNamespace(object_name=key, last_modified=datetime.now(UTC))

    def get_object(self, bucket: str, key: str):
        data = BytesIO(self.objects[key])
        return SimpleNamespace(
            read=data.read,
            close=lambda: None,
            release_conn=lambda: None,
        )

    def stat_object(self, bucket: str, key: str):
        if key not in self.objects:
            raise KeyError(key)
        return SimpleNamespace(object_name=key)

    def put_object(self, bucket: str, key: str, data, length: int, content_type: str = "") -> None:
        self.objects[key] = data.read()


@pytest.fixture()
def minio(monkeypatch) -> FakeMinio:
    fake = FakeMinio()
    monkeypatch.setattr(storage, "client", lambda: fake)
    tracing._discovery_cache.clear()
    return fake


@pytest.fixture()
def client(minio: FakeMinio) -> TestClient:
    return TestClient(app)


def _publish(minio: FakeMinio, domain: str = "construtoras", version: str = "v1.8.0") -> None:
    minio.objects[f"contratos/{domain}/{version}/contrato_semantico.json"] = json.dumps(CONTRACT).encode()


def test_home_serve_a_interface_estatica(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Gov Hub" in response.text
    assert "/static/js/main.js" in response.text


def test_visao_geral_exibe_os_conceitos_do_fluxo(client: TestClient) -> None:
    response = client.get("/visao-geral")
    assert response.status_code == 200
    assert "Contrato semântico" in response.text
    assert "Assinatura de layout" in response.text


def test_domains_lista_apenas_dominios_com_contrato(client: TestClient, minio: FakeMinio) -> None:
    _publish(minio)
    _publish(minio, domain="hospitais", version="v2.0.0")
    assert client.get("/api/domains").json() == ["construtoras", "hospitais"]


def test_contracts_lista_versoes_da_mais_recente_para_a_mais_antiga(client: TestClient, minio: FakeMinio) -> None:
    _publish(minio, version="v1.8.0")
    _publish(minio, version="v1.7.0")
    versions = [item["version"] for item in client.get("/api/contracts?domain=construtoras").json()]
    assert versions == ["v1.8.0", "v1.7.0"]


def test_publicar_contrato_grava_artefato_e_recusa_reenvio(client: TestClient, minio: FakeMinio) -> None:
    files = {"contract": ("contrato.json", json.dumps(CONTRACT).encode(), "application/json")}
    data = {"domain": "construtoras", "version": "v1.8.0"}

    created = client.post("/api/contracts", data=data, files=files)
    assert created.status_code == 200
    assert created.json()["version"] == "v1.8.0"
    assert "contratos/construtoras/v1.8.0/contrato.json" in minio.objects

    files = {"contract": ("contrato.json", json.dumps(CONTRACT).encode(), "application/json")}
    assert client.post("/api/contracts", data=data, files=files).status_code == 409


def test_publicar_contrato_recusa_versao_divergente(client: TestClient) -> None:
    files = {"contract": ("contrato.json", json.dumps(CONTRACT).encode(), "application/json")}
    response = client.post("/api/contracts", data={"domain": "construtoras", "version": "v2.0.0"}, files=files)
    assert response.status_code == 422


def test_upload_de_pdf_preserva_original_e_dispara_extracao(client: TestClient, minio: FakeMinio, monkeypatch) -> None:
    _publish(minio)
    monkeypatch.setattr(airflow, "trigger_extraction", lambda key: "manual__2026")

    response = client.post(
        "/api/documents",
        data={
            "domain": "construtoras",
            "entity_slug": "cury",
            "entity_name": "Cury",
            "contract_version": "v1.8.0",
        },
        files={"pdf": ("relatorio.pdf", b"%PDF-1.7 conteudo", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dag_run_id"] == "manual__2026"
    manifest = json.loads(minio.objects[payload["origin_manifest_key"]])
    assert manifest["status"] == "novo"
    assert manifest["entity_name"] == "Cury"
    assert manifest["versao_contrato_semantico"] == "v1.8.0"
    assert any(key.endswith("relatorio.pdf") for key in minio.objects)


def test_upload_recusa_arquivo_que_nao_e_pdf(client: TestClient, minio: FakeMinio) -> None:
    _publish(minio)
    response = client.post(
        "/api/documents",
        data={
            "domain": "construtoras",
            "entity_slug": "cury",
            "entity_name": "Cury",
            "contract_version": "v1.8.0",
        },
        files={"pdf": ("relatorio.pdf", b"nao e um pdf", "application/pdf")},
    )
    assert response.status_code == 422


def test_trace_mantem_rastreabilidade_quando_o_airflow_cai(client: TestClient, minio: FakeMinio, monkeypatch) -> None:
    document_id = "a" * 32
    prefix = f"execucoes/construtoras/extracao/cury/document_id={document_id}/execution_id=1"
    minio.objects[f"{prefix}/extraction/manifesto_execucao.json"] = json.dumps({"execution_id": "1"}).encode()

    def offline(*args, **kwargs):
        raise HTTPException(status_code=502, detail="Airflow indisponivel")

    monkeypatch.setattr(airflow, "access_token", offline)

    response = client.get(
        "/api/execution-trace",
        params={
            "domain": "construtoras",
            "entity_slug": "cury",
            "document_id": document_id,
            "dag_run_id": "manual__2026",
        },
    )

    assert response.status_code == 200
    trace = response.json()
    assert trace["stage"] == "evidence"
    assert trace["terminal"] is False
    assert "Airflow indisponivel" in trace["warning"]


def test_trace_conclui_quando_o_schema_resolvido_existe(client: TestClient, minio: FakeMinio, monkeypatch) -> None:
    document_id = "b" * 32
    extraction = f"execucoes/construtoras/extracao/cury/document_id={document_id}/execution_id=1"
    resolution = f"execucoes/construtoras/resolucao/cury/document_id={document_id}/execution_id=1"
    minio.objects[f"{extraction}/extraction/manifesto_execucao.json"] = json.dumps({"execution_id": "1"}).encode()
    minio.objects[f"{resolution}/resolution/schema_saida_resolvido.json"] = b"{}"

    def offline(*args, **kwargs):
        raise HTTPException(status_code=502, detail="Airflow indisponivel")

    monkeypatch.setattr(airflow, "access_token", offline)

    trace = client.get(
        "/api/execution-trace",
        params={
            "domain": "construtoras",
            "entity_slug": "cury",
            "document_id": document_id,
            "dag_run_id": "manual__2026",
        },
    ).json()

    assert trace["stage"] == "result"
    assert trace["terminal"] is True
