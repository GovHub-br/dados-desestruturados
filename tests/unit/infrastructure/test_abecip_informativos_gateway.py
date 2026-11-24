from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from document_processing.infrastructure.abecip import AbecipInformativosClient
from document_processing.infrastructure.llm.http_client import HttpResponse

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "abecip" / "informativos_mensais.html"


def _bloco(href: str, descricao: str, titulo: str = "Titulo", data: str = "01/01/2026") -> str:
    return (
        '<div class="bloco_noticia"><a href="{href}"><div class="txt_bloco_noticia">'
        '<span class="date">{data}</span><p>{titulo}</p>'
        '<span class="p_style_2">{descricao}</span></div></a></div>'
    ).format(href=href, descricao=descricao, titulo=titulo, data=data)


class _FakeHttp:
    def __init__(self, html: str) -> None:
        self.html = html
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def fetch(self, url: str, **kwargs: Any) -> HttpResponse:
        self.calls.append((url, kwargs))
        return HttpResponse(url=url, body=self.html.encode("utf-8"), content_type="text/html")


class AbecipInformativosClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = AbecipInformativosClient(http_client=_FakeHttp(""))  # type: ignore[arg-type]

    def test_lista_so_informativos_com_pdf_e_periodo_na_ordem_da_pagina(self) -> None:
        candidates = self.client.parse_page(FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual(
            [item["period_label"] for item in candidates],
            ["2026-08", "2026-03", "2025-12"],
        )

    def test_candidato_traz_identidade_de_origem_e_publicacao(self) -> None:
        agosto = self.client.parse_page(FIXTURE.read_text(encoding="utf-8"))[0]

        self.assertEqual(agosto["domain"], "abecip")
        self.assertEqual(agosto["entity_slug"], "abecip")
        self.assertEqual(agosto["company_slug"], "abecip")
        self.assertEqual(agosto["url"], "https://www.abecip.org.br/download?file=data-abecip-2026-08.pdf")
        self.assertEqual(agosto["title"], "Financiamentos imobiliários do SBPE somaram R$ 17 bilhões em agosto")
        self.assertEqual(agosto["published_at"], "2026-09-30")
        self.assertEqual(agosto["reference_year"], 2026)
        self.assertEqual(agosto["reference_quarter"], 0)
        self.assertTrue(agosto["should_trigger_dag2"])
        self.assertEqual(agosto["metadata"]["arquivo_origem"], "data-abecip-2026-08.pdf")
        self.assertEqual(agosto["metadata"]["periodo_origem"], "descricao")

    def test_sufixo_de_republicacao_no_arquivo_nao_muda_o_mes(self) -> None:
        marco = self.client.parse_page(FIXTURE.read_text(encoding="utf-8"))[1]

        self.assertEqual(marco["metadata"]["arquivo_origem"], "data-abecip-2026-032.pdf")
        self.assertEqual(marco["period_label"], "2026-03")
        self.assertEqual(marco["metadata"]["reference_month"], 3)

    def test_link_relativo_e_classe_com_espaco_extra_sao_aceitos(self) -> None:
        dezembro = self.client.parse_page(FIXTURE.read_text(encoding="utf-8"))[2]

        self.assertEqual(dezembro["url"], "https://www.abecip.org.br/download?file=data-abecip-2025-12-novo.pdf")
        self.assertEqual(dezembro["period_label"], "2025-12")

    def test_descricao_vence_o_nome_do_arquivo_e_o_conflito_fica_registrado(self) -> None:
        html = _bloco(
            "https://www.abecip.org.br/download?file=data-abecip-2026-04.pdf",
            "Em maio de 2026, os financiamentos somaram R$ 1 bilhao.",
        )

        candidate = self.client.parse_page(html)[0]

        self.assertEqual(candidate["period_label"], "2026-05")
        self.assertEqual(candidate["metadata"]["conflito_periodo_arquivo"], "2026-04")

    def test_sem_periodo_na_descricao_usa_o_nome_do_arquivo(self) -> None:
        html = _bloco(
            "https://www.abecip.org.br/download?file=data-abecip-2026-06.pdf",
            "Texto sem referencia ao periodo.",
        )

        candidate = self.client.parse_page(html)[0]

        self.assertEqual(candidate["period_label"], "2026-06")
        self.assertEqual(candidate["metadata"]["periodo_origem"], "nome_arquivo")

    def test_bloco_mal_fechado_nao_engole_o_seguinte(self) -> None:
        aberto = (
            '<div class="bloco_noticia"><a href="https://x.org/download?file=data-abecip-2026-01.pdf">'
            '<div class="txt_bloco_noticia"><span class="date">04/03/2026</span>'
            "<p>Janeiro</p><span class=\"p_style_2\">Em janeiro de 2026, algo.</span>"
        )
        seguinte = _bloco(
            "https://x.org/download?file=data-abecip-2026-02.pdf",
            "Em fevereiro de 2026, algo.",
        )

        candidates = self.client.parse_page(f"<div id=\"news_list\">{aberto}{seguinte}</div>")

        self.assertEqual([item["period_label"] for item in candidates], ["2026-01", "2026-02"])

    def test_mesmo_link_listado_duas_vezes_vira_um_candidato(self) -> None:
        bloco = _bloco(
            "https://x.org/download?file=data-abecip-2026-01.pdf",
            "Em janeiro de 2026, algo.",
        )

        self.assertEqual(len(self.client.parse_page(bloco + bloco)), 1)

    def test_pagina_sem_blocos_falha_em_vez_de_parecer_sem_novidades(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Nenhum informativo mensal reconhecido"):
            self.client.parse_page("<html><body><p>Manutencao</p></body></html>")

    def test_pagina_so_com_itens_nao_reconhecidos_tambem_falha(self) -> None:
        html = _bloco("https://x.org/noticias/evento", "Em setembro de 2026 acontece o congresso.")

        with self.assertRaisesRegex(RuntimeError, "1 bloco"):
            self.client.parse_page(html)

    def test_detect_candidates_baixa_a_pagina_de_imprensa_com_retentativas(self) -> None:
        http = _FakeHttp(FIXTURE.read_text(encoding="utf-8"))
        client = AbecipInformativosClient(http_client=http, max_attempts=4)  # type: ignore[arg-type]

        candidates = client.detect_candidates()

        self.assertEqual(len(candidates), 3)
        url, kwargs = http.calls[0]
        self.assertEqual(url, "https://www.abecip.org.br/imprensa/informativos-mensais")
        self.assertEqual(kwargs["max_attempts"], 4)


if __name__ == "__main__":
    unittest.main()
