#include "log_engine/muduo_parser.hpp"

#include <cassert>
#include <fstream>
#include <string>
#include <utility>

using namespace evidenceops::log_engine;

namespace {

LineParseResult parse(std::string text){
	const auto size=static_cast<std::uint64_t>(text.size());
	return parse_muduo_line(InputLine{20,std::move(text),size});
}

void expect_malformed(const std::string& text){
	const auto result=parse(text);
	assert(result.status==LineParseStatus::malformed);
	assert(!result.event&&!result.warnings.empty());
}

} // namespace

int main(int argument_count,char* arguments[]){
	const std::string message="TcpServer::newConnection [RpcProvider] - new connection [RpcProvider-127.0.0.1:8000#1] from 127.0.0.1:55596";
	const std::string sample="20261017 06:27:26.588995Z  5958 INFO  "+message+" - TcpServer.cc:80";
	const auto result=parse(sample);
	assert(result.status==LineParseStatus::parsed&&result.event);
	assert(result.warnings.empty());
	const auto& event=*result.event;
	assert(event.is_valid()&&event.format==LogFormat::muduo);
	assert(event.raw_time=="20261017 06:27:26.588995Z");
	assert(event.timestamp&&event.time_basis==TimeBasis::explicit_timezone);
	assert(event.timestamp->time_since_epoch().count()==1792218446588995LL);
	assert(event.level==LogLevel::info&&event.raw_level=="INFO");
	assert(event.thread_id=="5958"&&!event.process_id);
	assert(event.code_file=="TcpServer.cc"&&event.code_line==80);
	assert(!event.code_function&&event.event_index==0);
	assert(event.message==message&&event.raw_text==sample);
	assert(event.line_start==20&&event.line_end==20&&event.warnings.empty());

	const std::string suffix="  5958 INFO  ok - TcpServer.cc:80";
	assert(parse("19700101 00:00:00.000000Z"+suffix).event->timestamp->time_since_epoch().count()==0);
	assert(parse("19691231 23:59:59.999999Z"+suffix).event->timestamp->time_since_epoch().count()==-1);
	assert(parse("20000229 00:00:00.000001Z"+suffix).event->timestamp->time_since_epoch().count()==951782400000001LL);
	assert(parse("00010101 00:00:00.000000Z"+suffix).event->timestamp->time_since_epoch().count()==-62135596800000000LL);
	assert(parse("99991231 23:59:59.999999Z"+suffix).event->timestamp->time_since_epoch().count()==253402300799999999LL);
	for(const std::string time:{"20260229 06:27:26.588995Z","19000229 06:27:26.588995Z","20261317 06:27:26.588995Z","20261017 24:27:26.588995Z","20261017 06:60:26.588995Z","20261017 06:27:60.588995Z","20261017 06:27:26.58899xZ","20261017 06:27:26.588995X"})expect_malformed(time+suffix);
	const std::string header="20261017 06:27:26.588995Z";
	expect_malformed(header+" bad INFO  ok - TcpServer.cc:80");
	expect_malformed(header+" 18446744073709551616 INFO  ok - TcpServer.cc:80");
	expect_malformed(header+" 5958 INFO  ok");
	expect_malformed(header+" 5958 INFO  ok - :80");
	expect_malformed(header+" 5958 INFO  ok - TcpServer.cc:0");
	expect_malformed(header+" 5958 INFO  ok - TcpServer.cc:18446744073709551616");
	expect_malformed(header+" 5958 INFO ok - TcpServer.cc:80");
	assert(parse_muduo_line(InputLine{0,sample,0}).status==LineParseStatus::malformed);
	for(const std::string text:{"","   ","!!!","I20261017 14:27:33.117445 6099 client.cc:252] ok","2026-10-17 14:27:26,594:6099(0xabc):ZOO_INFO@check_events@2987: ok"}){
		const auto unmatched=parse(text);
		assert(unmatched.status==LineParseStatus::not_matched);
		assert(!unmatched.event&&unmatched.warnings.empty());
	}
	const auto mixed=parse(header+" 5958 wArN   Keep: 127.0.0.1:8000 - inner  - C:/rpc/Server.cc:80");
	assert(mixed.status==LineParseStatus::parsed);
	assert(mixed.event->level==LogLevel::warning&&mixed.event->raw_level=="wArN");
	assert(mixed.event->message==" Keep: 127.0.0.1:8000 - inner "&&mixed.event->code_file=="C:/rpc/Server.cc");
	for(const std::string level:{"TRACE","DEBUG","INFO ","WARN ","ERROR","FATAL"}){
		const auto known=parse(header+" 5958 "+level+" ok - Server.cc:1");
		assert(known.status==LineParseStatus::parsed&&known.event->level!=LogLevel::unknown);
	}
	const auto unknown=parse(header+" 5958 CUSTOM ok - Server.cc:1");
	assert(unknown.status==LineParseStatus::parsed&&unknown.event->level==LogLevel::unknown);
	assert(unknown.event->warnings.size()==1);
	assert(parse(header+" 5958 INFO   - Server.cc:1").event->message.empty());
	if(argument_count==2){
		std::ifstream input(arguments[1],std::ios::binary);
		assert(input);
		std::string line;
		std::uint64_t line_number=0,matched=0;
		while(std::getline(input,line)){
			++line_number;
			if(!line.empty()&&line.back()=='\r')line.pop_back();
			const auto parsed=parse_muduo_line(InputLine{line_number,line,static_cast<std::uint64_t>(line.size())});
			assert(parsed.status!=LineParseStatus::malformed);
			if(parsed.status==LineParseStatus::parsed){
				++matched;
				assert(parsed.event->timestamp&&parsed.event->raw_text==line);
			}
		}
		assert(input.eof()&&matched==220);
	}
	return 0;
}
