import json
import os
import re
import tempfile
import shutil
import unicodedata
from datetime import datetime,timezone
from pathlib import Path
from typing import Callable

from evidenceops.evaluation.core import summarize_results


def import_reviews(result_path:Path,review_path:Path)->dict:
	payload=load_result(result_path)
	data=json.loads(review_path.read_text(encoding="utf-8-sig"))
	if not isinstance(data,dict) or not isinstance(data.get("reviews"),list):
		raise ValueError("审核文件必须包含reviews数组")
	by_id={item["case_id"]:item for item in payload["results"]}
	seen=set()
	for review in data["reviews"]:
		if not isinstance(review,dict): raise ValueError("审核记录必须为对象")
		identity=review.get("case_id")
		if identity not in by_id or identity in seen: raise ValueError("审核案例不存在或重复")
		seen.add(identity)
		if review.get("status") not in ("passed","failed","disputed"): raise ValueError("审核状态无效")
		for key in ("reviewer","reason","model_version","prompt_version","corpus_hash"):
			if not isinstance(review.get(key),str) or not review[key].strip(): raise ValueError("审核记录缺少"+key)
		claims=review.get("claims")
		if not isinstance(claims,list): raise ValueError("审核记录必须包含claims数组")
		for claim in claims:
			if not isinstance(claim,dict) or not isinstance(claim.get("text"),str) or not claim["text"].strip(): raise ValueError("审核结论缺少正文")
			if claim.get("status") not in ("supported","unsupported","disputed"): raise ValueError("结论支持状态无效")
			if not isinstance(claim.get("evidence_ids"),list) or any(not isinstance(value,str) or not value.strip() for value in claim["evidence_ids"]): raise ValueError("结论证据ID无效")
			if not isinstance(claim.get("reason"),str) or not claim["reason"].strip(): raise ValueError("结论审核理由不能为空")
		visible={item["evidence_id"] for item in (by_id[identity].get("response") or {}).get("evidences",[])}
		if any(not set(claim["evidence_ids"])<=visible for claim in claims): raise ValueError("结论包含未知证据ID")
	for review in data["reviews"]:
		item=by_id[review["case_id"]]
		item["semantic_review"]={**item["semantic_review"],**review,"reviewed_at":datetime.now(timezone.utc).isoformat()}
	payload["summary"]={**payload.get("summary",{}),**summarize_results(payload["results"])}
	save_result(result_path,payload)
	return payload


def load_result(path:Path)->dict:
	payload=json.loads(path.read_text(encoding="utf-8-sig"))
	if not isinstance(payload,dict) or payload.get("schema_version")!=1:
		raise ValueError("评测结果必须声明schema_version=1")
	if not isinstance(payload.get("summary",{}),dict):
		raise ValueError("summary必须是对象")
	summarize_results(payload.get("results"))
	seen=set()
	# 开始交互前校验全部案例，避免审核到一半才发现文件结构损坏。
	for item in payload["results"]:
		case_id=item.get("case_id")
		if not isinstance(case_id,str) or not case_id.strip() or case_id in seen:
			raise ValueError("case_id不能为空或重复")
		if not isinstance(item.get("input"),str) or not item["input"].strip():
			raise ValueError("案例缺少description(input)")
		criteria=item["semantic_review"].get("criteria")
		if not isinstance(criteria,list) or not criteria or any(not isinstance(value,str) or not value.strip() for value in criteria):
			raise ValueError("案例缺少review_criteria(criteria)")
		response=item.get("response")
		if response is not None:
			if not isinstance(response,dict):
				raise ValueError("response必须是对象或null")
			report=response.get("report")
			if report is not None and (not isinstance(report,dict) or not isinstance(report.get("root_cause"),dict)
				or not isinstance(report["root_cause"].get("text"),str)):
				raise ValueError("模型报告缺少root_cause.text")
			if report is not None:
				claims=report.get("recommendations",[])
				if not isinstance(claims,list) or any(not isinstance(claim,dict) or not isinstance(claim.get("text"),str)
					or not isinstance(claim.get("evidence_ids",[]),list)
					or any(not isinstance(value,str) for value in claim.get("evidence_ids",[])) for claim in claims):
					raise ValueError("排查建议必须包含text和字符串证据ID数组")
		seen.add(case_id)
	return payload


def save_result(path:Path,payload:dict)->None:
	# 同目录临时文件写完后原子替换，写入失败不能把原JSON截断。
	temporary=None
	try:
		with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=path.parent,suffix=".tmp",delete=False) as output:
			temporary=Path(output.name)
			json.dump(payload,output,ensure_ascii=False,indent=2)
			output.write("\n")
			output.flush()
			os.fsync(output.fileno())
		os.replace(temporary,path)
	finally:
		if temporary is not None and temporary.exists():
			temporary.unlink()


def display_width(text:str)->int:
	# 中文通常占两个终端列；按len折行会让中文段落超过终端宽度。
	return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in ("W","F") else 1 for char in text)


def wrap_text(text:str,width:int)->list[str]:
	lines=[]
	for paragraph in text.expandtabs(4).split("\n"):
		line=""
		columns=0
		# 工具名和时间戳优先整体换行；只有超过整行宽度的长ID才拆分。
		for token in re.findall(r"[A-Za-z0-9_:/+.\-]+|\s+|.",paragraph):
			if display_width(token)<=width and columns+display_width(token)>width and line:
				lines.append(line)
				line=""
				columns=0
			for char in token:
				char_width=display_width(char)
				if columns+char_width>width and line:
					lines.append(line)
					line=""
					columns=0
				line+=char
				columns+=char_width
		lines.append(line)
	return lines


def render_case(item:dict,index:int,total:int,width:int)->list[str]:
	width=max(20,width)
	lines=["","─"*width,f"案例 {index:02d}/{total:02d}：{item['case_id']}","─"*width]
	def section(title:str,text:str)->None:
		lines.extend(["",title])
		lines.extend("  "+line for line in wrap_text(text,width-2))
	section("【诊断请求 / description】",item["input"])
	response=item.get("response") or {}
	report=response.get("report")
	section("【模型根因】",report["root_cause"]["text"] if report else "（无报告）")
	if report:
		lines.extend(["","【排查建议】"])
		for number,claim in enumerate(report.get("recommendations",[]),1):
			lines.extend("  "+line for line in wrap_text(f"{number}. {claim['text']}",width-2))
			lines.append("    引用证据：")
			for evidence_id in claim.get("evidence_ids",[]):
				lines.extend("    "+line for line in wrap_text(evidence_id,width-4))
			lines.append("")
		section("【证据局限 / limitations】",str(report.get("limitations","")))
	else:
		error=response.get("error_detail") or {}
		section("【执行状态与错误】",f"状态：{response.get('status','无响应')}\n"
			f"错误码：{error.get('code',response.get('error_code')) or item.get('execution_error') or '无'}\n"
			f"错误说明：{error.get('message','无')}")
	section("【规则检查】","通过" if item["rule_passed"] else "未通过")
	failed=[check["name"] for check in item.get("checks",[]) if not check["passed"]]
	if failed:
		lines.extend("  "+line for line in wrap_text("未通过项："+", ".join(failed),width-2))
	lines.extend(["","【审核标准 / review_criteria】"])
	for number,criterion in enumerate(item["semantic_review"]["criteria"],1):
		lines.extend("  "+line for line in wrap_text(f"{number}. {criterion}",width-2))
	lines.append("")
	return lines


def review_result(path:Path,read:Callable=input,write:Callable=print)->dict:
	payload=load_result(path)
	width=min(100,shutil.get_terminal_size(fallback=(100,24)).columns)
	for index,item in enumerate(payload["results"],1):
		review=item["semantic_review"]
		# 已审核案例保留原判定，让中断后再次运行能继续剩余案例。
		if review["status"]!="pending":
			continue
		for line in render_case(item,index,len(payload["results"]),width):
			write(line)
		while True:
			answer=read("符合全部审核标准吗？[y/n]：").strip().lower()
			if answer in ("y","n"):
				break
			write("请输入y或n；Ctrl+C可退出，已完成的审核会保留。")
		comment=read("comment（可留空）：").strip()
		review.update(status="passed" if answer=="y" else "failed",comment=comment)
		payload["summary"]={**payload.get("summary",{}),**summarize_results(payload["results"])}
		save_result(path,payload)
	payload["summary"]={**payload.get("summary",{}),**summarize_results(payload["results"])}
	save_result(path,payload)
	for name in ("rule_pass_rate","semantic_pass_rate","final_pass_rate"):
		write(f"{name}: {payload['summary'][name]:.2%}")
	write(f"待审核案例：{payload['summary']['semantic_review_pending']}")
	return payload
