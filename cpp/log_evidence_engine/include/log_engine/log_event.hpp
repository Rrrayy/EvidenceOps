#pragma once

#include <chrono>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>
#include <variant>

namespace evidenceops::log_engine {

enum class LogFormat {
	glog,
	zookeeper,
	muduo,
	plain,
	unknown,
};

enum class LogLevel {
	trace,
	debug,
	info,
	warning,
	error,
	fatal,
	unknown,
};

enum class TimeBasis {
	explicit_timezone,
	input_timezone,
	unknown,
};

enum class SourceRole {
	server,
	client,
	unknown,
};

using MicrosecondTime=std::chrono::time_point<std::chrono::system_clock,std::chrono::microseconds>;
using EventAttribute=std::variant<std::int64_t,std::uint64_t,bool,std::string>;

std::string normalize_token(std::string_view value);
std::string to_string(LogFormat value);
std::string to_string(LogLevel value);
std::string to_string(TimeBasis value);
std::string to_string(SourceRole value);
LogFormat parse_log_format(std::string_view value);
LogLevel parse_log_level(std::string_view value);
SourceRole parse_source_role(std::string_view value);

struct LogEvent {
	std::uint64_t event_index=0;
	LogFormat format=LogFormat::unknown;
	std::string raw_time;
	std::optional<MicrosecondTime> timestamp;
	TimeBasis time_basis=TimeBasis::unknown;
	std::optional<LogLevel> level;
	std::optional<std::string> raw_level;
	std::string message;
	std::optional<std::string> event_kind;
	std::map<std::string,EventAttribute> attributes;
	std::optional<std::uint64_t> process_id;
	std::optional<std::string> thread_id;
	std::optional<std::string> code_file;
	std::optional<std::string> code_function;
	std::optional<std::uint64_t> code_line;
	std::uint64_t line_start=0;
	std::uint64_t line_end=0;
	std::string raw_text;
	std::vector<std::string> warnings;

	bool is_valid() const noexcept;
};

struct SourceInfo {
	std::string source_id;
	SourceRole source_role=SourceRole::unknown;
	std::optional<std::string> service_name;
	std::optional<std::string> environment;
	std::string input_sha256;
	std::string hash_basis="not_computed";
};

struct ParseStatistics {
	std::uint64_t input_bytes=0;
	std::uint64_t event_count=0;
	std::uint64_t unrecognized_count=0;
	std::uint64_t warning_count=0;
	std::uint64_t skipped_blank_lines=0;
	bool stopped_early=false;
	std::optional<std::string> stop_reason;
};

struct ParseResult {
	std::string schema_version="log-evidence-v1";
	SourceInfo source;
	std::vector<LogEvent> events;
	ParseStatistics statistics;
};

} // namespace evidenceops::log_engine
