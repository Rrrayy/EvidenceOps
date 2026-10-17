#pragma once

#include "log_engine/line_parse_result.hpp"

namespace evidenceops::log_engine {

struct EngineOptions {
	std::string input_path;
	SourceInfo source;
	ReaderLimits reader_limits;
	std::uint64_t max_events=10000;
	std::uint64_t max_output_bytes=16*1024*1024;
};

struct EngineOutput {
	std::string json;
	int exit_code=1;
};

LineParseResult parse_line(const InputLine& input);
EngineOutput run_engine(const EngineOptions& options);

} // namespace evidenceops::log_engine
