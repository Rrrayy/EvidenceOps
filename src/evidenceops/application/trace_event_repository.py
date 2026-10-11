from typing import Protocol


class TraceEventRepository(Protocol):
	def create(self,event:dict)->None:
		...

	def list_by_run(self,run_id:str,after_sequence:int=0,limit:int=100)->tuple[dict,...]:
		...

	def get_max_sequence(self,run_id:str)->int:
		...
