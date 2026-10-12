"""负责顺序执行 Playwright CLI 验收并保存可核查的结果和日志。"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

workspace=Path(__file__).resolve().parents[2]
output=workspace/"output"/"playwright"/"audit-results"
output.mkdir(parents=True,exist_ok=True)
command=shutil.which("npx")
if not command: raise SystemExit("需要 Node.js 和 npx")
suites=("smoke","failures","reconnect","model-connections","storage","storage-failures","audit-regressions","audit-boundaries","audit-operations")
selected=tuple(sys.argv[1:]) or suites
if any(name not in suites for name in selected): raise SystemExit("未知验收组")
results=json.loads((output/"results.json").read_text(encoding="utf-8")) if sys.argv[1:] and (output/"results.json").exists() else []
for name in selected:
	process=subprocess.run([command,"--yes","--package","@playwright/cli","playwright-cli","-s=evidenceops","run-code",f"--filename=frontend/tests/browser-{name}.js"],cwd=workspace,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120)
	log=process.stdout+process.stderr
	(output/f"{name}.log").write_text(log,encoding="utf-8")
	try:
		result=json.loads(log.split("### Result\n",1)[1].split("\n###",1)[0])
		if process.returncode or not result.get("passed"): raise ValueError("浏览器未确认通过")
	except (IndexError,ValueError) as error:
		results.append({"suite":name,"passed":False,"error":str(error)})
		(output/"results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
		raise SystemExit(f"FAIL {name}: 查看 {output/name}.log")
	results=[item for item in results if item["suite"]!=name]
	results.append({"suite":name,**result})
	(output/"results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
	print(f"PASS {name}",flush=True)
print(f"本次 {len(selected)} 组通过；累计记录 {len(results)} 组",flush=True)
