# Python 模块导入失败排查

适用范围：Python 3 程序启动或运行时报 ModuleNotFoundError、ImportError，包括 No module named pandas。本文为 EvidenceOps 原创排障练习摘要，不是本次故障事实，也不是已验证的修复结论；不适用于 RPC 超时、JVM 内存错误或 Go 数据竞争。

Python 的 ModuleNotFoundError 表示导入时未找到模块，不能仅凭错误断定服务器从未安装对应软件包。需要保留完整 traceback、缺失模块名、启动命令、Python 版本以及运行环境；缺失项可能是直接导入的模块，也可能是已安装包的传递依赖。

Python 导入检查应先核对实际解释器：用运行服务的同一个 Python 执行 python -c "import sys; print(sys.executable); print(sys.path)"，再用该解释器执行 python -m pip --version 和 python -m pip show pandas。比较 IDE、终端、虚拟环境、容器及服务进程的解释器；另一个环境里安装成功不代表当前服务可导入。

若确认当前 Python 环境缺少 pandas，应按项目依赖文件和锁定版本，在正确虚拟环境中安装并验证导入，再补充启动回归。python -m pip 将 pip 绑定到指定解释器；不要未核对环境就执行全局安装、sudo pip 或升级全部依赖。导入名和发行包名不总相同，不能对任意模块名机械执行同名 pip install。

Python 模块已存在却导入失败时，还需检查工作目录、同名本地文件遮蔽、sys.path、包目录结构以及扩展模块二进制依赖。没有 traceback、解释器路径和包清单时，应明确证据不足；不能引用 RPC 重试配置来解释 Python 导入失败，也不能承诺安装一定修复。

参考来源（2026-10-15 核对）：Python 官方 ModuleNotFoundError 定义 https://docs.python.org/3/library/exceptions.html#ModuleNotFoundError ；pip 官方解释器调用方式 https://pip.pypa.io/en/stable/user_guide/#running-pip 。命令仅为人工核查建议，Agent 不应自动执行安装。
