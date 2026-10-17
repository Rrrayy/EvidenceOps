#include "log_engine/glog_parser.hpp"
#include "log_engine/zookeeper_parser.hpp"

#include <cassert>
#include <string>
#include <utility>

using namespace evidenceops::log_engine;

namespace {

LineParseResult parse(std::string text){
	const auto size=static_cast<std::uint64_t>(text.size());
	return parse_glog_line(InputLine{18,std::move(text),size});
}

void expect_malformed(const std::string& text){
	const auto result=parse(text);
	assert(result.status==LineParseStatus::malformed);
	assert(!result.event);
	assert(!result.warnings.empty());
}

} // namespace

int main(){
	const std::string sample="I20261017 14:27:33.117445  6099 client.cc:252] Total requests: 100000";
	const auto result=parse(sample);
	assert(result.status==LineParseStatus::parsed);
	assert(result.event&&result.warnings.empty());
	const auto& event=*result.event;
	assert(event.is_valid());
	assert(event.format==LogFormat::glog);
	assert(event.raw_time=="20261017 14:27:33.117445");
	assert(!event.timestamp&&event.time_basis==TimeBasis::unknown);
	assert(event.level==LogLevel::info&&event.raw_level=="I");
	assert(event.thread_id=="6099");
	assert(!event.process_id&&!event.code_function);
	assert(event.code_file=="client.cc"&&event.code_line==252);
	assert(event.line_start==18&&event.line_end==18);
	assert(event.raw_text==sample);
	assert(event.message=="Total requests: 100000");
	assert(event.event_index==0&&event.warnings.size()==1);

	for(const std::string text:{"","   ","!!!","WARNING: Logging before InitGoogleLogging() is written to STDERR","2026-10-17 14:27:26,594:6099(0xabc):ZOO_INFO@check_events@2987: ok","I1017 14:27:33.117445 6099 client.cc:252] no year"}){
		const auto unmatched=parse(text);
		assert(unmatched.status==LineParseStatus::not_matched);
		assert(!unmatched.event&&unmatched.warnings.empty());
	}
	const std::string header="I20261017 14:27:33.117445 ";
	expect_malformed(header+"bad client.cc:252] ok");
	expect_malformed(header+"18446744073709551616 client.cc:252] ok");
	expect_malformed(header+"6099 client.cc:18446744073709551616] ok");
	expect_malformed(header+"6099 client.cc:0] ok");
	expect_malformed(header+"6099 client.cc:252");
	expect_malformed(header+"6099 :252] ok");
	expect_malformed(header+"6099 client.cc:252]missing space");
	expect_malformed("I20260229 14:27:33.117445 6099 client.cc:252] ok");
	expect_malformed("I20261017 24:27:33.117445 6099 client.cc:252] ok");
	expect_malformed("I20261017 14:27:33.11744x 6099 client.cc:252] ok");
	assert(parse("I20240229 14:27:33.117445 6099 client.cc:252] ok").status==LineParseStatus::parsed);
	assert(parse_glog_line(InputLine{0,sample,0}).status==LineParseStatus::malformed);

	const auto warning=parse("w20261017 14:27:33.117445	6099	C:/rpc/client.cc:252]  Keep: 127.0.0.1:2181  ");
	assert(warning.status==LineParseStatus::parsed);
	assert(warning.event->level==LogLevel::warning&&warning.event->raw_level=="w");
	assert(warning.event->code_file=="C:/rpc/client.cc");
	assert(warning.event->message==" Keep: 127.0.0.1:2181  ");
	assert(parse("E20261017 14:27:33.117445 6099 client.cc:252] error").event->level==LogLevel::error);
	assert(parse("F20261017 14:27:33.117445 6099 client.cc:252] fatal").event->level==LogLevel::fatal);
	assert(parse(header+"6099 client.cc:252]").event->message.empty());
	assert(parse_zookeeper_line(InputLine{18,sample,0}).status==LineParseStatus::not_matched);
	return 0;
}
