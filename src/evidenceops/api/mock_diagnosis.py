from uuid import uuid4  # 为每次 HTTP 请求生成 request_id

from fastapi import FastAPI  # 创建 HTTP 应用
from pydantic import BaseModel,field_validator  # 定义并校验请求数据
from starlette.responses import JSONResponse  # 指定成功或失败的 HTTP 状态码
from pydantic import Field  # 限制请求日志长度

from evidenceops.mocks.request_log import RequestLogEvidenceCollector,RequestLogReportGenerator  # 注入本次请求的日志案例
from evidenceops.application.diagnosis_response import to_response  # 将内部结果转换为响应数据
from evidenceops.application.diagnosis_service import DiagnosisService  # 调用已有业务流程
from evidenceops.domain.diagnosis_run import RunStatus  # 判断运行结果
from evidenceops.mocks.rpc_timeout import MockRpcEvidenceCollector,MockRpcReportGenerator  # 注入固定 Mock 案例


class MockDiagnosisRequest(BaseModel):  # 定义该接口接受的 JSON 请求
	description:str  # 当前只接收故障描述，不接收尚未使用的日志

	@field_validator("description")  # 对 description 增加业务校验
	@classmethod  # Pydantic 会通过类调用这个校验方法
	def validate_description(cls,description:str)->str:  # 接收输入并返回有效描述
		if not description.strip():  # 拒绝空字符串和纯空白字符串
			raise ValueError("description不能为空")  # FastAPI 将其转换为 422 响应
		return description.strip()  # 去掉首尾空白后传给 Service

class RequestLogDiagnosisRequest(BaseModel):  # 定义日志驱动的 Mock 请求
	description:str  # 用户希望排查的问题
	log_text:str=Field(max_length=20000)  # 限制一次提交的日志文本长度

	@field_validator("description","log_text")  # 两个字段都不能只包含空白
	@classmethod  # 让 Pydantic 调用该校验方法
	def validate_nonblank(cls,value:str)->str:  # 接收一个已通过字符串类型检查的字段
		if not value.strip():  # 空字符串和纯空白文本都无效
			raise ValueError("输入不能为空")  # FastAPI 返回 422
		return value  # 保留原始日志文本，避免改变哈希对应的内容

def create_app(service:DiagnosisService)->FastAPI:  # 用指定 Service 创建应用，方便测试注入失败依赖
	app=FastAPI()  # 创建 HTTP 应用对象

	@app.post("/api/v1/mock/diagnosis")  # 将下面的函数绑定到 Mock 诊断路径
	def diagnose(request:MockDiagnosisRequest)->JSONResponse:  # FastAPI 先校验请求，再执行此函数
		request_id=f"req-{uuid4()}"  # 服务端生成当前请求的追踪 ID
		result=service.execute(request_id,request.description)  # 调用现有诊断流程
		response=to_response(result)  # 转换 Run、Evidence、Report
		status_code=200 if result.run.status is RunStatus.SUCCEEDED else 503  # 根据运行终态选择 HTTP 状态码
		return JSONResponse(status_code=status_code,content=response)  # 将普通数据编码为 JSON 并发送

	@app.post("/api/v1/mock/log-diagnosis")  # 明确这是日志驱动的 Mock 入口
	def diagnose_request_log(request:RequestLogDiagnosisRequest)->JSONResponse:  # FastAPI 先完成请求校验
		collector=RequestLogEvidenceCollector(request.log_text)  # 为本次请求单独保存日志
		service_for_request=DiagnosisService(collector,RequestLogReportGenerator())  # 组装本次诊断依赖
		request_id=f"req-{uuid4()}"  # 生成本次 HTTP 请求 ID
		result=service_for_request.execute(request_id,request.description)  # 复用已有 Service 闭环
		response=to_response(result)  # 转换内部对象为 JSON 可用数据
		status_code=200 if result.run.status is RunStatus.SUCCEEDED else 503  # 暂时沿用当前 Mock 接口的状态码约定
		return JSONResponse(status_code=status_code,content=response)  # 返回本次输入产生的结果
	return app  # 返回已注册路由的应用


app=create_app(DiagnosisService(MockRpcEvidenceCollector(),MockRpcReportGenerator()))  # 默认应用使用固定 Mock 案例