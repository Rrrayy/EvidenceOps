import pytest # 使用每条用例独立的配置目录。


@pytest.fixture(autouse=True) # 全套回归不得读取或改变用户保存的连接与默认值。
def isolate_connections(monkeypatch,tmp_path):
	monkeypatch.setenv("EVIDENCEOPS_CONNECTIONS_DIR",str(tmp_path/"model-connections")) # 隔离模型连接、验证结果和凭据文件。
