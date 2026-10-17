#include "log_engine/log_event.hpp"

#include <cassert>

using namespace evidenceops::log_engine;

int main(){
	assert(normalize_token(" ZooKeeper ")=="zookeeper");
	assert(normalize_token("Zoo Keeper")=="zoo keeper");
	assert(normalize_token("GLOG")=="glog");
	assert(parse_log_format("MuDuO")==LogFormat::muduo);
	assert(parse_log_level(" WARN ")==LogLevel::warning);
	assert(parse_source_role("CLIENT")==SourceRole::client);
	assert(to_string(LogFormat::zookeeper)=="zookeeper");

	LogEvent event;
	event.event_index=1;
	event.line_start=10;
	event.line_end=10;
	event.raw_text="sample";
	assert(event.is_valid());
	assert(!event.event_kind&&event.attributes.empty());
	event.event_kind="contract_test";
	event.attributes.emplace("signed_value",std::int64_t{-7});
	event.attributes.emplace("count",std::uint64_t{100});
	event.attributes.emplace("finished",true);
	event.attributes.emplace("label",std::string("sample"));
	assert(std::get<std::int64_t>(event.attributes.at("signed_value"))==-7);
	assert(std::get<std::uint64_t>(event.attributes.at("count"))==100);
	assert(std::get<bool>(event.attributes.at("finished")));
	assert(std::get<std::string>(event.attributes.at("label"))=="sample");

	event.line_end=9;
	assert(!event.is_valid());
	return 0;
}
