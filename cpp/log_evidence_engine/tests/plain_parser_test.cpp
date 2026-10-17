#include "log_engine/plain_parser.hpp"

#include <cassert>
#include <string>
#include <utility>

using namespace evidenceops::log_engine;

namespace {

LineParseResult parse(std::string text){
	const auto size=static_cast<std::uint64_t>(text.size());
	return parse_plain_line(InputLine{17,std::move(text),size});
}

void expect_malformed(const std::string& text){
	const auto result=parse(text);
	assert(result.status==LineParseStatus::malformed);
	assert(!result.event&&!result.warnings.empty());
}

} // namespace

int main(){
	const auto duration=parse("CallMethod returned in 18319 us");
	assert(duration.status==LineParseStatus::parsed&&duration.event);
	const auto& event=*duration.event;
	assert(event.is_valid()&&event.format==LogFormat::plain);
	assert(event.event_kind=="call_return");
	assert(std::get<std::uint64_t>(event.attributes.at("duration_us"))==18319);
	assert(event.attributes.size()==1);
	assert(event.message=="CallMethod returned in 18319 us"&&event.raw_text==event.message);
	assert(event.line_start==17&&event.line_end==17&&event.event_index==0);
	assert(!event.timestamp&&event.time_basis==TimeBasis::unknown&&event.raw_time.empty());
	assert(!event.level&&!event.raw_level&&!event.process_id&&!event.thread_id);
	assert(!event.code_file&&!event.code_function&&!event.code_line);
	assert(event.warnings.size()==1&&duration.warnings.empty());
	const auto async=parse("async rpc completed, errcode=0");
	assert(async.status==LineParseStatus::parsed&&async.event->event_kind=="async_result");
	assert(std::get<std::int64_t>(async.event->attributes.at("errcode"))==0);
	assert(std::get<std::int64_t>(parse("async rpc completed, errcode=-7").event->attributes.at("errcode"))==-7);
	assert(std::get<std::int64_t>(parse("async rpc completed, errcode=-9223372036854775808").event->attributes.at("errcode"))==(-9223372036854775807LL-1));
	const auto batch=parse("Async batch completed=100 failed=0 expected=100 finished=1");
	assert(batch.status==LineParseStatus::parsed&&batch.event->event_kind=="async_batch");
	assert(batch.event->attributes.size()==4);
	assert(std::get<std::uint64_t>(batch.event->attributes.at("completed"))==100);
	assert(std::get<std::uint64_t>(batch.event->attributes.at("failed"))==0);
	assert(std::get<std::uint64_t>(batch.event->attributes.at("expected"))==100);
	assert(std::get<bool>(batch.event->attributes.at("finished")));
	assert(!std::get<bool>(parse("Async batch completed=0 failed=0 expected=100 finished=0").event->attributes.at("finished")));
	assert(std::get<std::uint64_t>(parse("CallMethod returned in 18446744073709551615 us").event->attributes.at("duration_us"))==18446744073709551615ULL);
	for(const std::string text:{"CallMethod returned in 18446744073709551616 us","CallMethod returned in -1 us","CallMethod returned in 1 us extra","CallMethod returned in us","async rpc completed, errcode=abc","async rpc completed, errcode=9223372036854775808","async rpc completed, errcode=-9223372036854775809","async rpc completed, errcode=0 trailing","Async batch completed=100 failed=0 expected=100 finished=2","Async batch completed=100 failed=0 expected=100 finished=1 trailing","Async batch completed=-1 failed=0 expected=100 finished=1","Async batch completed=1 expected=1 finished=1"})expect_malformed(text);
	assert(parse_plain_line(InputLine{0,"CallMethod returned in 1 us",0}).status==LineParseStatus::malformed);
	for(const std::string text:{"","  \t","!!!","[ConsistentHash] node updated","WARNING: Logging before InitGoogleLogging() is written to STDERR"}){
		const auto unmatched=parse(text);
		assert(unmatched.status==LineParseStatus::not_matched);
		assert(!unmatched.event&&unmatched.warnings.empty());
	}
	const InputLine input{23,"  unrecognized: payload  ",25};
	const auto unknown=make_unknown_event(input);
	assert(unknown&&unknown->is_valid()&&unknown->format==LogFormat::unknown);
	assert(unknown->raw_text==input.text&&unknown->message==input.text);
	assert(unknown->line_start==23&&unknown->line_end==23);
	assert(!unknown->timestamp&&!unknown->event_kind&&unknown->attributes.empty());
	assert(unknown->warnings.size()==2);
	assert(!make_unknown_event(InputLine{0,"text",4}));
	assert(!make_unknown_event(InputLine{1," \t\r\n",4}));
	assert(!make_unknown_event(InputLine{1,"",0}));
	assert(make_unknown_event(InputLine{1,"!!!",3}));
	return 0;
}
