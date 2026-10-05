from datetime import datetime
from typing import Any


def parse_query_time(value:Any,field:str)->datetime:
	if not isinstance(value,str):
		raise ValueError(f"{field}必须是带时区的ISO 8601字符串，例如2026-10-05T10:00:00+08:00")
	try:
		timestamp=datetime.fromisoformat(value)
	except ValueError as error:
		raise ValueError(f"{field}时间格式无效；需要带时区的ISO 8601字符串，例如2026-10-05T10:00:00+08:00") from error
	if timestamp.tzinfo is None or timestamp.utcoffset() is None:
		raise ValueError(f"{field}必须携带时区，例如+08:00")
	return timestamp
