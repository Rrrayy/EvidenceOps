#pragma once

#include "log_engine/bounded_reader.hpp"
#include "log_engine/log_event.hpp"

#include <optional>
#include <string>
#include <vector>

namespace evidenceops::log_engine {

enum class LineParseStatus {
	not_matched,
	parsed,
	malformed,
};

struct LineParseResult {
	LineParseStatus status=LineParseStatus::not_matched;
	std::optional<LogEvent> event;
	std::vector<std::string> warnings;
};

} // namespace evidenceops::log_engine
