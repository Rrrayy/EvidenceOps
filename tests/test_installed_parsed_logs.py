"""验证安装入口按实际装配与维护状态声明日志能力，且不暴露文件路径。"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from evidenceops.api.agent_app import build_agent_app
from evidenceops.api.installed_app import create_installed_app


def test_installed_parser_capabilities_follow_readiness(tmp_path,monkeypatch):
	monkeypatch.delenv("EVIDENCEOPS_PERSISTENCE",raising=False)
	source=tmp_path/"private.log"
	source.write_text("async rpc completed, errcode=0\n",encoding="utf-8")
	manifest=tmp_path/"sources.json"
	manifest.write_text(json.dumps([{"source_id":"rpc-server","path":str(source),"role":"server"}]),encoding="utf-8")
	monkeypatch.setenv("EVIDENCEOPS_LOG_SOURCES_FILE",str(manifest))
	monkeypatch.setenv("EVIDENCEOPS_LOG_PARSER_BINARY",str(Path(__file__)))
	with TestClient(create_installed_app(tmp_path/"installation",build_agent_app)) as client:
		installation=client.app.state.installation
		response=client.get("/api/v1/agent/capabilities")
		assert response.json()["parsed_logs"] is True
		assert response.json()["parsed_log_sources"]==["rpc-server"]
		assert str(source) not in response.text and "private.log" not in response.text
		installation.maintenance=True
		assert client.get("/api/v1/agent/capabilities").json()["parsed_log_sources"]==[]
		assert client.get("/api/v1/agent/capabilities").json()["parsed_logs"] is False
		installation.maintenance=False
		installation.state="degraded"
		assert client.get("/api/v1/agent/capabilities").json()["parsed_logs"] is False
		installation.state="ready"
	monkeypatch.delenv("EVIDENCEOPS_LOG_SOURCES_FILE")
	with TestClient(create_installed_app(tmp_path/"without-parser",build_agent_app)) as client:
		capabilities=client.get("/api/v1/agent/capabilities").json()
		assert capabilities["parsed_logs"] is False and capabilities["parsed_log_sources"]==[]
