from datetime import date
from unittest.mock import patch

import pytest

from document_processing.application.use_cases.documents.historical_ingestion import (
    historical_parameters,
)
from document_processing.infrastructure.ri.ri_results_gateway import RiResultsClient


def test_unknown_domain_and_inverted_dates_are_rejected():
    with pytest.raises(ValueError):
        historical_parameters({"dominio": "outro"})
    with pytest.raises(ValueError):
        historical_parameters({
            "dominio": "ambos", "data_inicial": "2026-12-01", "data_final": "2026-01-01",
        })


def test_company_and_quarter_filters_are_applied_before_discovery():
    client = RiResultsClient()
    with patch.object(client, "detect_operational_previews", return_value=[]) as detect:
        client.detect_historical_previews(date(2025, 12, 1), date(2026, 3, 31), ["cury"])
    assert [(call.kwargs["window"].year, call.kwargs["window"].quarter) for call in detect.call_args_list] == [
        (2025, 4), (2026, 1),
    ]
    assert all([source.slug for source in call.kwargs["sources"]] == ["cury"] for call in detect.call_args_list)
    with pytest.raises(ValueError, match="desconhecidas"):
        client.detect_historical_previews(date(2026, 1, 1), date(2026, 3, 31), ["inexistente"])
