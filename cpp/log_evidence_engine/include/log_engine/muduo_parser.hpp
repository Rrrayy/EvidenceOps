#pragma once

#include "log_engine/line_parse_result.hpp"

namespace evidenceops::log_engine {

LineParseResult parse_muduo_line(const InputLine& input);

} // namespace evidenceops::log_engine
