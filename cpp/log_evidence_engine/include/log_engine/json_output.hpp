#pragma once

#include "log_engine/log_event.hpp"

namespace evidenceops::log_engine {

std::string event_json(const LogEvent& event,std::uint64_t limit);
std::string result_envelope(const SourceInfo& source,const ParseStatistics& statistics,
	std::string_view status,std::string_view error,std::uint64_t limit);

} // namespace evidenceops::log_engine
