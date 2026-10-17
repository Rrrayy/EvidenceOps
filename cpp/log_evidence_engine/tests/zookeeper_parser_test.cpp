#include "log_engine/zookeeper_parser.hpp"

#include <cassert>
#include <string>
#include <utility>

using namespace evidenceops::log_engine;

namespace {

LineParseResult parse(std::string text){
	const auto size=static_cast<std::uint64_t>(text.size());
	return parse_zookeeper_line(InputLine{12,std::move(text),size});
}

void expect_malformed(const std::string& text){
	const auto result=parse(text);
	assert(result.status==LineParseStatus::malformed);
	assert(!result.event);
	assert(!result.warnings.empty());
}

} // namespace

int main(){
	const std::string sample="2026-10-17 14:27:26,594:6099(0x7f400c5ff6c0):ZOO_INFO@check_events@2987: initiated connection to server 127.0.0.1:2181";
	const auto result=parse(sample);
	assert(result.status==LineParseStatus::parsed);
	assert(result.event);
	assert(result.warnings.empty());
	const auto& event=*result.event;
	assert(event.is_valid());
	assert(event.format==LogFormat::zookeeper);
	assert(event.raw_time=="2026-10-17 14:27:26,594");
	assert(!event.timestamp);
	assert(event.time_basis==TimeBasis::unknown);
	assert(event.level==LogLevel::info);
	assert(event.raw_level=="ZOO_INFO");
	assert(event.process_id==6099);
	assert(event.thread_id=="0x7f400c5ff6c0");
	assert(event.code_function=="check_events");
	assert(event.code_line==2987);
	assert(!event.code_file);
	assert(event.line_start==12&&event.line_end==12);
	assert(event.event_index==0);
	assert(event.raw_text==sample);
	assert(event.message=="initiated connection to server 127.0.0.1:2181");
	assert(event.warnings.size()==1);

	for(const std::string text:{"","   ","!!!","I20261017 14:27:26.596709 6099 client.cc:52] ok","ordinary text:ZOO_INFO"}){
		const auto unmatched=parse(text);
		assert(unmatched.status==LineParseStatus::not_matched);
		assert(!unmatched.event&&unmatched.warnings.empty());
	}

	const std::string header="2026-10-17 14:27:26,594:";
	const std::string tail="(0xabc):ZOO_INFO@check_events@2987: ok";
	expect_malformed(header+"bad"+tail);
	expect_malformed(header+"18446744073709551616"+tail);
	expect_malformed(header+"6099(0xZZ):ZOO_INFO@check_events@2987: ok");
	expect_malformed(header+"6099(0xabc):ZOO_INFO@check_events@18446744073709551616: ok");
	expect_malformed(header+"6099(0xabc):ZOO_INFO@check_events@0: ok");
	expect_malformed(header+"6099(0xabc):ZOO_INFO@check_events");
	expect_malformed(header+"6099(0xabc):ZOO_INFO@@2987: ok");
	expect_malformed("2026-02-29 14:27:26,594:6099"+tail);
	expect_malformed("2026-10-17 24:27:26,594:6099"+tail);
	expect_malformed("2026-13-17 14:27:26,594:6099"+tail);
	assert(parse("2024-02-29 14:27:26,594:6099"+tail).status==LineParseStatus::parsed);
	assert(parse_zookeeper_line(InputLine{0,sample,0}).status==LineParseStatus::malformed);

	const auto mixed=parse(header+"6099(0XAbC):zOo_iNfO@Check_Events@2987:  Keep: 127.0.0.1:2181  ");
	assert(mixed.status==LineParseStatus::parsed);
	assert(mixed.event->level==LogLevel::info);
	assert(mixed.event->raw_level=="zOo_iNfO");
	assert(mixed.event->code_function=="Check_Events");
	assert(mixed.event->message==" Keep: 127.0.0.1:2181  ");
	const auto unknown=parse(header+"6099(0xabc):ZOO_CUSTOM@check_events@2987: ok");
	assert(unknown.status==LineParseStatus::parsed);
	assert(unknown.event->level==LogLevel::unknown);
	assert(unknown.event->warnings.size()==2);
	assert(parse(header+"6099(0xabc):ZOO_INFO@check_events@2987:").event->message.empty());
	return 0;
}
