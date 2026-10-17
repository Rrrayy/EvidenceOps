#pragma once

#include "log_engine/line_parse_result.hpp"

namespace evidenceops::log_engine {

LineParseResult parse_plain_line(const InputLine& input);
std::optional<LogEvent> make_unknown_event(const InputLine& input);

} // namespace evidenceops::log_engine
