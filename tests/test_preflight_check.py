#
# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License 2.0;
# you may not use this file except in compliance with the Elastic License 2.0.
#
from copy import deepcopy
from unittest.mock import patch

import pytest

from connectors.preflight_check import PreflightCheck
from connectors.protocol import CONCRETE_CONNECTORS_INDEX, CONCRETE_JOBS_INDEX

headers = {"X-Elastic-Product": "Elasticsearch"}
host = "http://localhost:9200"
config = {
    "elasticsearch": {
        "host": host,
        "username": "elastic",
        "password": "changeme",
        "max_wait_duration": 0.1,
        "initial_backoff_duration": 0.1,
    },
    "service": {"preflight_max_attempts": 4, "preflight_idle": 0.1},
    "connectors": [
        {
            "connector_id": "connector_1",
            "service_type": "some_type",
        },
    ],
}


def mock_es_info(mock_responses, healthy=True, repeat=False):
    status = 200 if healthy else 503
    mock_responses.get(host, status=status, headers=headers, repeat=repeat)


def mock_index_exists(mock_responses, index, exist=True, repeat=False):
    status = 200 if exist else 404
    mock_responses.head(f"{host}/{index}", status=status, repeat=repeat)


def mock_index(mock_responses, index, doc_id, repeat=False):
    status = 200
    mock_responses.put(f"{host}/{index}/_doc/{doc_id}", status=status, repeat=repeat)


def mock_delete(mock_responses, index, doc_id, repeat=False):
    status = 200
    mock_responses.delete(f"{host}/{index}/_doc/{doc_id}", status=status, repeat=repeat)


@pytest.mark.asyncio
async def test_es_unavailable(mock_responses):
    mock_es_info(mock_responses, healthy=False, repeat=True)
    preflight = PreflightCheck(config)
    result = await preflight.run()
    assert result is False


@pytest.mark.asyncio
async def test_connectors_index_missing(mocker, mock_responses):
    doc_id = ".connectors-create-doc"
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX, exist=False)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX, exist=True)
    mock_index(mock_responses, CONCRETE_CONNECTORS_INDEX, doc_id)
    mock_delete(mock_responses, CONCRETE_CONNECTORS_INDEX, doc_id)
    preflight = PreflightCheck(config)
    spy = mocker.spy(preflight.es_client.client, "index")
    delete_spy = mocker.spy(preflight.es_client.client, "delete")
    await preflight.run()
    spy.assert_called_with(index=CONCRETE_CONNECTORS_INDEX, document={}, id=doc_id)
    delete_spy.assert_called_with(index=CONCRETE_CONNECTORS_INDEX, id=doc_id)


@pytest.mark.asyncio
async def test_jobs_index_missing(mocker, mock_responses):
    doc_id = ".connectors-create-doc"
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX, exist=True)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX, exist=False)
    mock_index(mock_responses, CONCRETE_JOBS_INDEX, doc_id)
    mock_delete(mock_responses, CONCRETE_JOBS_INDEX, doc_id)
    preflight = PreflightCheck(config)
    spy = mocker.spy(preflight.es_client.client, "index")
    delete_spy = mocker.spy(preflight.es_client.client, "delete")
    await preflight.run()
    spy.assert_called_with(index=CONCRETE_JOBS_INDEX, document={}, id=doc_id)
    delete_spy.assert_called_with(index=CONCRETE_JOBS_INDEX, id=doc_id)


@pytest.mark.asyncio
async def test_both_indices_missing(mocker, mock_responses):
    doc_id = ".connectors-create-doc"
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX, exist=False)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX, exist=False)
    mock_index(mock_responses, CONCRETE_CONNECTORS_INDEX, doc_id)
    mock_index(mock_responses, CONCRETE_JOBS_INDEX, doc_id)
    mock_delete(mock_responses, CONCRETE_CONNECTORS_INDEX, doc_id)
    mock_delete(mock_responses, CONCRETE_JOBS_INDEX, doc_id)
    preflight = PreflightCheck(config)
    spy = mocker.spy(preflight.es_client.client, "index")
    delete_spy = mocker.spy(preflight.es_client.client, "delete")
    await preflight.run()
    assert spy.call_count == 2
    assert delete_spy.call_count == 2


@pytest.mark.asyncio
async def test_pass(mock_responses):
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX)
    preflight = PreflightCheck(config)
    result = await preflight.run()
    assert result is True


@pytest.mark.asyncio
async def test_es_transient_error(mock_responses):
    mock_es_info(mock_responses, healthy=False)
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX)
    preflight = PreflightCheck(config)
    result = await preflight.run()
    assert result is True


@pytest.mark.asyncio
async def test_index_exist_transient_error(mock_responses):
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX, exist=False)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX, repeat=True)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX, exist=False)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX, repeat=True)
    preflight = PreflightCheck(config)
    result = await preflight.run()
    assert result is True


@pytest.mark.asyncio
@patch("connectors.preflight_check.logger")
async def test_native_config_is_warned(patched_logger, mock_responses):
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX)
    local_config = deepcopy(config)
    local_config["native_service_types"] = ["foo", "bar"]
    del local_config["connectors"]
    preflight = PreflightCheck(local_config)
    result = await preflight.run()
    assert result is True
    patched_logger.warning.assert_any_call(
        "The configuration 'native_service_types' has been deprecated. Please remove this configuration."
    )
    patched_logger.warning.assert_any_call(
        "Native Connectors are only supported internal to Elastic Cloud deployments, which this process is not."
    )
    patched_logger.warning.assert_any_call(
        "Please update your config.yml to configure at least one connector"
    )


@pytest.mark.asyncio
@patch("connectors.preflight_check.logger")
async def test_native_config_is_forced(patched_logger, mock_responses):
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX)
    local_config = deepcopy(config)
    local_config["native_service_types"] = ["foo", "bar"]
    local_config["_force_allow_native"] = True
    preflight = PreflightCheck(local_config)
    result = await preflight.run()
    assert result is True
    patched_logger.warning.assert_not_called()


@pytest.mark.asyncio
@patch("connectors.preflight_check.logger")
async def test_client_config(patched_logger, mock_responses):
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX)
    local_config = deepcopy(config)
    local_config["connectors"][0]["connector_id"] = "foo"
    local_config["connectors"][0]["service_type"] = "bar"
    preflight = PreflightCheck(local_config)
    result = await preflight.run()
    assert result is True
    patched_logger.warning.assert_not_called()


@pytest.mark.asyncio
@patch("connectors.preflight_check.logger")
async def test_unmodified_default_config(patched_logger, mock_responses):
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX)
    local_config = deepcopy(config)
    local_config["connectors"][0]["connector_id"] = "changeme"
    local_config["connectors"][0]["service_type"] = "changeme"
    preflight = PreflightCheck(local_config)
    result = await preflight.run()
    assert result is False
    patched_logger.errorassert_any_call(
        "In your configuration, you must change 'connector_id' and 'service_type' to not be 'changeme'"
    )


@pytest.mark.asyncio
@patch("connectors.preflight_check.logger")
async def test_missing_mode_config(patched_logger, mock_responses):
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX)
    local_config = deepcopy(config)
    del local_config["connectors"]
    preflight = PreflightCheck(local_config)
    result = await preflight.run()
    assert result is False
    patched_logger.errorassert_any_call("You must configure at least one connector")


@pytest.mark.asyncio
@patch("connectors.preflight_check.logger")
async def test_extraction_service_enabled_and_found_writes_info_log(
    patched_logger, mock_responses
):
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX)
    local_config = deepcopy(config)
    local_config["extraction_service"] = {"host": "http://localhost:8090"}
    preflight = PreflightCheck(local_config)

    mock_responses.get(
        f"{local_config['extraction_service']['host']}/ping/", status=200
    )

    result = await preflight.run()
    assert result is True

    patched_logger.info.assert_any_call(
        f"Data extraction service found at {local_config['extraction_service']['host']}."
    )


@pytest.mark.asyncio
@patch("connectors.preflight_check.logger")
async def test_extraction_service_enabled_but_missing_logs_warning(
    patched_logger, mock_responses
):
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX)
    local_config = deepcopy(config)
    local_config["extraction_service"] = {"host": "http://localhost:8090"}
    preflight = PreflightCheck(local_config)

    mock_responses.get(
        f"{local_config['extraction_service']['host']}/ping/", status=404
    )

    result = await preflight.run()
    assert result is True

    patched_logger.warning.assert_any_call(
        f"Data extraction service was found at {local_config['extraction_service']['host']} but health-check returned `404'."
    )


@pytest.mark.asyncio
@patch("connectors.preflight_check.logger")
async def test_extraction_service_enabled_but_missing_logs_critical(
    patched_logger, mock_responses
):
    mock_es_info(mock_responses)
    mock_index_exists(mock_responses, CONCRETE_CONNECTORS_INDEX)
    mock_index_exists(mock_responses, CONCRETE_JOBS_INDEX)
    local_config = deepcopy(config)
    local_config["extraction_service"] = {"host": "http://localhost:8090"}
    preflight = PreflightCheck(local_config)

    result = await preflight.run()
    assert result is True

    patched_logger.critical.assert_any_call(
        f"Expected to find a running instance of data extraction service at {local_config['extraction_service']['host']} but failed. Connection refused: GET {local_config['extraction_service']['host']}/ping/."
    )
