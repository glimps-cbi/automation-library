import pytest
import os
import json
from glimps.models import GlimpsConfiguration, ProfileStatus
from glimps.get_status_action import GetStatus
from unittest.mock import patch
import requests


@pytest.mark.skipif("'GLIMPS_API_KEY' not in os.environ.keys()")
def test_integration_get_status():
    action = GetStatus()
    action.module.configuration = GlimpsConfiguration(
        api_key=os.environ["GLIMPS_API_KEY"], base_url="https://gmalware.ggp.glimps.re"
    )

    response: ProfileStatus = action.run({})
    assert response is not None
    assert response.get("daily_quota", 0) > 0


def test_get_status_error(token):
    action = GetStatus()
    action.module.configuration = GlimpsConfiguration(
        api_key=token, base_url="https://gmalware.ggp.glimps.re"
    )

    with patch("gdetect.api.Client._request") as mock:
        r = requests.Response()
        http_resp = {"status": False, "error": "unauthorized"}
        r._content = json.dumps(http_resp).encode("utf-8")
        r.status_code = 401
        mock.return_value = r

        response = action.run({})
        assert response.get("daily_quota") == 0
        assert response.get("available_daily_quota") == 0
        assert response.get("estimated_analysis_duration") == 0


def test_get_status_ok(token):
    action = GetStatus()
    action.module.configuration = GlimpsConfiguration(
        api_key=token, base_url="https://gmalware.ggp.glimps.re"
    )

    with patch("gdetect.api.Client._request") as mock:
        r = requests.Response()
        http_resp = {
            "daily_quota": 10,
            "available_daily_quota": 15,
            "estimated_analysis_duration": 100,
        }
        r._content = json.dumps(http_resp).encode("utf-8")
        r.status_code = 200
        mock.return_value = r

        response = action.run({})
        assert response.get("daily_quota") == 10
        assert response.get("available_daily_quota") == 15
        assert response.get("estimated_analysis_duration") == 100
        assert response.get("cache") is False