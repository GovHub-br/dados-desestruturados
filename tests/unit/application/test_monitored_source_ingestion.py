from __future__ import annotations

import hashlib
import json
import unittest
from types import SimpleNamespace
from typing import Any

from document_processing.application.use_cases.documents import MonitoredSourceIngestionUseCase
from document_processing.infrastructure.llm.http_client import HttpClient, HttpResponse

BUCKET = "ocr-cidades"
CONTRACT_KEY = "contratos/abecip/v2.3.0/contrato_semantico_abecip.json"
CONTRACT_URI = f"minio://{BUCKET}/{CONTRACT_KEY}"
PDF_AGOSTO = b"%PDF-1.7 informativo de agosto"
PDF_JUNHO = b"%PDF-1.7 informativo de junho"


class _FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {CONTRACT_KEY: b"{}"}
        self.writes: list[str] = []
        self.identities = {}

    def reserve_document_id(self, domain, entity, digest, proposed):
        return self.identities.setdefault((domain, entity, digest), proposed)

    def object_exists(self, object_key: str) -> bool:
        return object_key in self.objects

    def put_bytes(self, *, object_key: str, data: bytes, content_type: str = "") -> str:
        self.objects[object_key] = data
        self.writes.append(object_key)
        return f"minio://{BUCKET}/{object_key}"

    def put_json(self, *, object_key: str, payload: dict[str, Any]) -> str:
        return self.put_bytes(
            object_key=object_key, data=json.dumps(payload).encode("utf-8"), content_type="json"
        )

    def get_json(self, *, object_key: str) -> dict[str, Any]:
        return json.loads(self.objects[object_key])

    def list_object_keys(self, *, prefix: str, suffix: str | None = None) -> list[str]:
        return sorted(
            key
            for key in self.objects
            if key.startswith(prefix) and (suffix is None or key.endswith(suffix))
        )


class _FakeHttp:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def fetch(self, url: str, **_: Any) -> HttpResponse:
        return HttpResponse(url=url, body=self.files[url], content_type="application/pdf")

    filename_from_url = staticmethod(HttpClient.filename_from_url)


class _FakeSource:
    def __init__(self, candidates: list[dict[str, Any]]) -> None:
        self.candidates = candidates

    def detect_candidates(self) -> list[dict[str, Any]]:
        return self.candidates


def _candidate(period: str, **overrides: Any) -> dict[str, Any]:
    year, month = period.split("-")
    candidate = {
        "domain": "abecip",
        "entity_slug": "abecip",
        "entity_name": "ABECIP",
        "company_slug": "abecip",
        "company_name": "ABECIP",
        "title": f"Informativo {period}",
        "url": f"https://www.abecip.org.br/download?file=data-abecip-{period}.pdf",
        "provider": "abecip_informativos_mensais",
        "source_url": "https://www.abecip.org.br/imprensa/informativos-mensais",
        "period_label": period,
        "reference_year": int(year),
        "reference_quarter": 0,
        "should_trigger_dag2": True,
        "metadata": {"arquivo_origem": f"data-abecip-{period}.pdf", "reference_month": int(month)},
        "contrato_semantico_uri": CONTRACT_URI,
        "versao_contrato_semantico": "2.3.0",
    }
    candidate.update(overrides)
    return candidate


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class MonitoredSourceIngestionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.minio = _FakeMinio()
        self.files = {
            "https://www.abecip.org.br/download?file=data-abecip-2026-08.pdf": PDF_AGOSTO,
            "https://www.abecip.org.br/download?file=data-abecip-2026-06.pdf": PDF_JUNHO,
        }
        self.config = SimpleNamespace(
            minio_bucket=BUCKET,
            minio_extract_prefix="execucoes/construtoras/extracao",
            ri_download_timeout_seconds=1,
            ri_download_max_attempts=1,
            ri_download_retry_delay_seconds=0,
            force_extract=False,
        )

    def _use_case(self, candidates: list[dict[str, Any]]) -> MonitoredSourceIngestionUseCase:
        return MonitoredSourceIngestionUseCase(
            source=_FakeSource(candidates),
            http_client=_FakeHttp(self.files),  # type: ignore[arg-type]
            config=self.config,  # type: ignore[arg-type]
            minio_client=self.minio,  # type: ignore[arg-type]
        )

    def _agosto_dir(self) -> str:
        document_id = _digest(PDF_AGOSTO)[:32]
        matching = [
            key.rsplit("/", 1)[0] for key in self.minio.objects
            if key.endswith(".pdf") and key.rsplit("/", 1)[-1].startswith(_digest(PDF_AGOSTO)[:16])
        ]
        return matching[0] if matching else f"documentos-origem/abecip/abecip/ano=2026/periodo=2026-08/document_id={document_id}"

    def _add_extraction(self, period: str, content: bytes) -> None:
        from document_processing.domain.document_identity import document_id_from_key
        origin = next(
            (key for key in self.minio.objects if key.endswith(".pdf") and key.rsplit("/", 1)[-1].startswith(_digest(content)[:16])),
            "",
        )
        document_id = document_id_from_key(origin, _digest(content))
        year = period.split("-")[0]
        artifact = f"execucoes/abecip/teste/{document_id}/inventory.json"
        self.minio.objects[artifact] = b"{}"
        self.minio.objects[
            f"execucoes/abecip/extracao/abecip/ano={year}/periodo={period}/document_id={document_id}/"
            "execution_id=x/extraction/manifesto_execucao.json"
        ] = json.dumps({"artifact_uris": [f"minio://{BUCKET}/{artifact}"]}).encode()

    def test_documento_novo_e_gravado_num_diretorio_proprio_e_segue_para_extracao(self) -> None:
        use_case = self._use_case([_candidate("2026-08")])

        [result] = use_case.persist_new_documents(use_case.detect_candidates())

        directory = self._agosto_dir()
        self.assertEqual(
            self.minio.writes,
            [
                f"{directory}/{_digest(PDF_AGOSTO)[:16]}_data-abecip-2026-08.pdf",
                f"{directory}/documento_detectado.json",
            ],
        )
        self.assertEqual(self.minio.objects[self.minio.writes[0]], PDF_AGOSTO)
        self.assertEqual(result["status"], "novo")
        self.assertTrue(result["should_extract"])
        self.assertEqual(result["origin_manifest_key"], f"{directory}/documento_detectado.json")
        self.assertRegex(result["document_id"], r"^20\d{2}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}Z__" + _digest(PDF_AGOSTO)[:32] + "$")

    def test_manifesto_de_origem_carrega_o_que_as_dags_seguintes_leem(self) -> None:
        use_case = self._use_case([_candidate("2026-08")])
        [result] = use_case.persist_new_documents(use_case.detect_candidates())

        manifest = self.minio.get_json(object_key=result["origin_manifest_key"])

        self.assertEqual(manifest["dominio"], "abecip")
        self.assertEqual(manifest["contrato_semantico_uri"], CONTRACT_URI)
        self.assertTrue(manifest["should_trigger_dag2"])
        self.assertEqual(manifest["candidate"]["period_label"], "2026-08")
        self.assertEqual(manifest["candidate"]["entity_slug"], "abecip")
        self.assertTrue(manifest["pdf_uri"].startswith(f"minio://{BUCKET}/{self._agosto_dir()}/"))

    def test_segunda_execucao_nao_grava_nada_e_repete_o_pedido_enquanto_nao_ha_extracao(self) -> None:
        use_case = self._use_case([_candidate("2026-08")])
        use_case.persist_new_documents(use_case.detect_candidates())
        writes_depois_da_primeira = list(self.minio.writes)

        [result] = use_case.persist_new_documents(use_case.detect_candidates())

        self.assertEqual(self.minio.writes, writes_depois_da_primeira)
        self.assertEqual(result["status"], "duplicado")
        self.assertTrue(result["should_extract"])

    def test_documento_ja_extraido_nao_volta_para_a_fila(self) -> None:
        use_case = self._use_case([_candidate("2026-08")])
        use_case.persist_new_documents(use_case.detect_candidates())
        self._add_extraction("2026-08", PDF_AGOSTO)

        [result] = use_case.persist_new_documents(use_case.detect_candidates())

        self.assertEqual(result["status"], "duplicado")
        self.assertFalse(result["should_extract"])
        self.assertTrue(result["extraction_already_exists"])

    def test_force_extract_do_ambiente_nao_reextrai_o_que_ja_foi_extraido(self) -> None:
        self.config.force_extract = True
        use_case = self._use_case([_candidate("2026-08")])
        use_case.persist_new_documents(use_case.detect_candidates())
        self._add_extraction("2026-08", PDF_AGOSTO)

        [result] = use_case.persist_new_documents(use_case.detect_candidates())

        self.assertFalse(result["should_extract"])

    def test_pdf_de_carga_manual_e_reconhecido_pelo_checksum_e_nao_e_duplicado(self) -> None:
        digest = _digest(PDF_JUNHO)
        manual_keys = {
            "layout_document_id": f"documentos-origem/abecip/abecip/document_id={digest[:32]}/{digest[:16]}_x.pdf",
            "layout_prefixado": f"documentos-origem/abecip/abecip/ano=2026/periodo=maio/{digest[:16]}_x.pdf",
        }
        for name, key in manual_keys.items():
            with self.subTest(name):
                self.minio.objects = {CONTRACT_KEY: b"{}", key: PDF_JUNHO}
                self.minio.writes.clear()
                use_case = self._use_case([_candidate("2026-06")])

                [result] = use_case.persist_new_documents(use_case.detect_candidates())

                self.assertEqual(result["status"], "duplicado_externo")
                self.assertFalse(result["should_extract"])
                self.assertEqual(result["origin_manifest_key"], "")
                self.assertEqual(result["pdf_uri"], f"minio://{BUCKET}/{key}")
                self.assertEqual(self.minio.writes, [])

    def test_mesmo_mes_com_conteudo_diferente_e_um_documento_novo(self) -> None:
        digest = _digest(b"%PDF-1.7 captura antiga")
        self.minio.objects[
            f"documentos-origem/abecip/abecip/document_id={digest[:32]}/{digest[:16]}_x.pdf"
        ] = b"%PDF-1.7 captura antiga"
        use_case = self._use_case([_candidate("2026-06")])

        [result] = use_case.persist_new_documents(use_case.detect_candidates())

        self.assertEqual(result["status"], "novo")
        self.assertTrue(result["should_extract"])

    def test_resposta_que_nao_e_pdf_falha_sem_gravar_nada(self) -> None:
        self.files["https://www.abecip.org.br/download?file=data-abecip-2026-08.pdf"] = (
            b"<html>erro 500</html>"
        )
        use_case = self._use_case([_candidate("2026-08")])

        with self.assertRaisesRegex(RuntimeError, "nao retornou um PDF"):
            use_case.persist_new_documents(use_case.detect_candidates())

        self.assertEqual(self.minio.writes, [])

    def test_manifesto_perdido_entre_o_pdf_e_o_json_e_refeito(self) -> None:
        use_case = self._use_case([_candidate("2026-08")])
        use_case.persist_new_documents(use_case.detect_candidates())
        manifest_key = f"{self._agosto_dir()}/documento_detectado.json"
        del self.minio.objects[manifest_key]
        self.minio.writes.clear()

        [result] = use_case.persist_new_documents(use_case.detect_candidates())

        self.assertEqual(self.minio.writes, [manifest_key])
        self.assertEqual(result["origin_manifest_key"], manifest_key)
        self.assertTrue(result["should_extract"])

    def test_mesmo_conteudo_em_dois_links_da_mesma_execucao_e_gravado_uma_vez(self) -> None:
        self.files["https://www.abecip.org.br/download?file=data-abecip-2026-09.pdf"] = PDF_AGOSTO
        use_case = self._use_case([_candidate("2026-08"), _candidate("2026-09")])

        results = use_case.persist_new_documents(use_case.detect_candidates())

        self.assertEqual([item["status"] for item in results], ["novo", "duplicado_externo"])
        self.assertEqual(len([key for key in self.minio.writes if key.endswith(".pdf")]), 1)

    def test_contrato_ausente_no_candidato_usa_o_mais_novo_do_dominio(self) -> None:
        self.minio.objects["contratos/abecip/v2.8.0/contrato_semantico_abecip.json"] = b"{}"
        candidate = _candidate("2026-08")
        del candidate["contrato_semantico_uri"]
        del candidate["versao_contrato_semantico"]
        use_case = self._use_case([candidate])

        [result] = use_case.persist_new_documents(use_case.detect_candidates())

        self.assertEqual(
            result["candidate"]["contrato_semantico_uri"],
            f"minio://{BUCKET}/contratos/abecip/v2.8.0/contrato_semantico_abecip.json",
        )
        self.assertEqual(result["candidate"]["versao_contrato_semantico"], "2.8.0")

    def test_inspect_candidate_nao_grava_nada(self) -> None:
        use_case = self._use_case([_candidate("2026-08")])

        inspected = use_case.inspect_candidate(_candidate("2026-08"))

        self.assertEqual(inspected.status, "novo")
        self.assertTrue(inspected.should_extract)
        self.assertEqual(self.minio.writes, [])


if __name__ == "__main__":
    unittest.main()


class HistoricalIngestionTest(unittest.TestCase):
    def setUp(self):
        from document_processing.application.use_cases.documents.historical_ingestion import (
            HistoricalIngestionUseCase,
        )

        self.base = MonitoredSourceIngestionTest()
        self.base.setUp()
        self.base.config.minio_resolution_prefix = "execucoes/construtoras/resolucao"
        self.ingestion = self.base._use_case([])
        self.ingestion.reuse_existing_origins = True
        self.history = HistoricalIngestionUseCase(
            abecip_source=_FakeSource([]), ri_source=None, ingestion=self.ingestion,
        )

    def test_reuses_legacy_pdf_and_recovers_missing_extraction(self):
        digest = _digest(PDF_AGOSTO)
        key = f"documentos-origem/abecip/abecip/document_id={digest[:32]}/{digest[:16]}_antigo.pdf"
        self.base.minio.objects[key] = PDF_AGOSTO

        result = self.history.persist_candidate(_candidate("2026-08"))

        self.assertEqual(result["document_id"], digest[:32])
        self.assertTrue(result["should_extract"])
        self.assertFalse(result["resolution_complete"])
        self.assertTrue(result["origin_manifest_key"].startswith(key.rsplit("/", 1)[0]))
        self.assertFalse(any(key.endswith(".pdf") for key in self.base.minio.writes))

    def test_complete_extraction_is_reused_and_missing_resolution_is_forwarded(self):
        first = self.history.persist_candidate(_candidate("2026-08"))
        self.base._add_extraction("2026-08", PDF_AGOSTO)
        writes = list(self.base.minio.writes)

        result = self.history.persist_candidate(_candidate("2026-08"))

        self.assertEqual(result["document_id"], first["document_id"])
        self.assertFalse(result["should_extract"])
        self.assertTrue(result["extraction_manifest_key"])
        self.assertFalse(result["resolution_complete"])
        self.assertEqual(writes, self.base.minio.writes)

    def test_incomplete_extraction_is_retried(self):
        self.history.persist_candidate(_candidate("2026-08"))
        self.base._add_extraction("2026-08", PDF_AGOSTO)
        key = next(key for key in self.base.minio.objects if key.endswith("/inventory.json"))
        del self.base.minio.objects[key]

        result = self.history.persist_candidate(_candidate("2026-08"))

        self.assertTrue(result["should_extract"])
        self.assertEqual(result["extraction_manifest_key"], "")

    def test_published_resolution_is_skipped(self):
        first = self.history.persist_candidate(_candidate("2026-08"))
        self.base._add_extraction("2026-08", PDF_AGOSTO)
        extraction = next(key for key in self.base.minio.objects if key.endswith("/manifesto_execucao.json"))
        manifest = self.base.minio.get_json(object_key=extraction)
        manifest["execution_id"] = "run-original"
        self.base.minio.objects[extraction] = json.dumps(manifest).encode()
        prefix = f"fallback/abecip/abecip/document_id={first['document_id']}/execution_id=fallback/"
        self.base.minio.objects[prefix + "layout_signature_candidato.json"] = json.dumps({
            "execution_id_origem": "run-original",
        }).encode()
        self.base.minio.objects[prefix + "publicacao_layout_signature.json"] = json.dumps({
            "status": "publicado",
            "candidate_layout_object_key": prefix + "layout_signature_candidato.json",
        }).encode()

        result = self.history.persist_candidate(_candidate("2026-08"))

        self.assertFalse(result["should_extract"])
        self.assertTrue(result["resolution_complete"])

    def test_extractor_preserves_timestamp_document_id(self):
        from document_processing.application.use_cases.documents import (
            SourceDocumentProcessingUseCase,
        )

        result = self.history.persist_candidate(_candidate("2026-08"))
        minio = self.base.minio
        minio.get_bytes = lambda *, object_key: minio.objects[object_key]
        config = self.base.config
        config.pipeline_tmp_dir = "/tmp"
        use_case = SourceDocumentProcessingUseCase(config=config, minio_client=minio)
        from unittest.mock import patch
        with patch.object(use_case, "_write_temp_pdf", return_value="/tmp/test.pdf"):
            doc = use_case._build_origin_document(
                object_key=result["pdf_uri"].split("/", 3)[3], origin_prefix="documentos-origem",
            )
        self.assertEqual(doc["document_id"], result["document_id"])
