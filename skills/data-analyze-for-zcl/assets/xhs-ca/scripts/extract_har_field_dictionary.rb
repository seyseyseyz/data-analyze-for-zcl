#!/usr/bin/env ruby

require "base64"
require "csv"
require "digest"
require "fileutils"
require "json"
require "set"
require "uri"

OUTPUT_DIR = File.expand_path("../output", __dir__)

EXPLANATION_KEYS = %w[
  tooltip toolTip description desc definition explanation helpText remark compareText
].freeze
API_EXPLANATION_KEYS = %w[explainText explanation description desc tooltip toolTip definition remark].freeze
LABEL_KEYS = %w[label title name metricLabel fieldName columnTitle key].freeze

def decode_response(entry)
  content = entry.dig("response", "content") || {}
  text = content["text"].to_s
  return nil if text.empty?

  text = Base64.strict_decode64(text) if content["encoding"] == "base64"
  text = text.force_encoding(Encoding::UTF_8)
  text.valid_encoding? ? text : nil
rescue ArgumentError
  nil
end

def unescape_js(value)
  value = value.encode(Encoding::UTF_8, invalid: :replace, undef: :replace)
  value = value.gsub(/\\u[0-9a-fA-F]{4}/, " ")
  value = value.gsub(/\\x[0-9a-fA-F]{2}/, " ")
  value.gsub(/\\([\\'"nrt])/) do
    { "n" => "\n", "r" => "\r", "t" => "\t" }.fetch($1, $1)
  end
end

def strip_markup(value)
  value.to_s.gsub(/<[^>]*>/, " ").gsub(/&(?:nbsp|ensp|emsp);/i, " ")
end

def extract_properties(source)
  properties = []
  [
    /([A-Za-z_$][\w$]*)\s*:\s*"((?:\\.|[^"\\])*)"/m,
    /([A-Za-z_$][\w$]*)\s*:\s*'((?:\\.|[^'\\])*)'/m
  ].each do |pattern|
    source.to_enum(:scan, pattern).each do
      match = Regexp.last_match
      properties << [match.begin(0), match[1], unescape_js(match[2])]
    end
  end
  properties.sort_by(&:first)
end

def classify(field, explanation, key)
  prompt = explanation.match?(/\A(?:请|点击|获取|暂无|加载|确认|失败|不支持|已解决|未解决|非常|一般|满意)/)
  campaign = explanation.match?(/借助活动|权益|团员|返现|入团券|红包/)
  metric = explanation.match?(/统计|期间|近\s*\d+|用户|人数|金额|件数|支付|成交|客单价|占比|ROI|转化|指标|口径|累计|去重/)
  time_rule = key == "compareText" || explanation.match?(/周期|对比|查询|较前|可选时间范围/)

  return "ordinary_prompt" if prompt
  return "campaign_rule_or_example" if campaign
  return "time_comparison_definition" if time_rule
  return "metric_definition" if metric
  return "field_or_option_definition"
end

def confidence(key, source_url)
  return "high" if %w[tooltip toolTip definition explanation].include?(key)
  return "medium" if %w[description desc helpText remark compareText].include?(key)
  return "low" if source_url.include?("vendors") || source_url.include?("library-")

  "medium"
end

def schema_safe_endpoint?(url)
  path = URI.parse(url).path
  return false if path.match?(%r{/cs/|/wario/|/redbreast/|/sec/|/burdock/|/chat|im_token|profile})

  path.start_with?("/api/data", "/api/edith/")
rescue URI::InvalidURIError
  false
end

def schema_value_type(value)
  case value
  when Hash then "object"
  when Array then "array"
  when String then "string"
  when Numeric then "number"
  when TrueClass, FalseClass then "boolean"
  when NilClass then "null"
  else value.class.name
  end
end

def collect_schema(value, path, output, depth = 0)
  return if depth > 8

  if value.is_a?(Hash)
    value.each do |key, child|
      next if key.to_s.match?(/token|cookie|authorization|secret|password|avatar|image|url/i)
      child_path = path.empty? ? key.to_s : "#{path}.#{key}"
      output << [child_path, key.to_s, schema_value_type(child)]
      collect_schema(child, child_path, output, depth + 1)
    end
  elsif value.is_a?(Array)
    value.first(3).each { |child| collect_schema(child, "#{path}[]", output, depth + 1) }
  end
end

def collect_api_metrics(value, source, output, path = "")
  if value.is_a?(Hash)
    title = value["title"] || value["name"] || value["label"]
    explanation_key = API_EXPLANATION_KEYS.find { |key| value[key].is_a?(String) && value[key].match?(/[\p{Han}]/) }
    if title.is_a?(String) && title.match?(/[\p{Han}]/) && explanation_key
      modules = Array(value["modules"]).map do |item|
        next unless item.is_a?(Hash)
        [item["moduleFirst"], item["moduleSecond"]].compact.reject(&:empty?).join("/")
      end.compact.uniq
      output << {
        "field" => title,
        "explanation" => value[explanation_key],
        "classification" => value.key?("metricId") ? "metric_definition" : "api_field_definition",
        "confidence" => value.key?("metricId") ? "high" : "medium",
        "source_key" => explanation_key,
        "metric_id" => value["metricId"],
        "modules" => modules.join("; "),
        "online" => value["online"],
        "source_har" => source[0],
        "har_entry" => source[1],
        "source_url" => source[2]
      }
    end
    value.each { |key, child| collect_api_metrics(child, source, output, "#{path}.#{key}") }
  elsif value.is_a?(Array)
    value.each { |child| collect_api_metrics(child, source, output, "#{path}[]") }
  end
end

if ARGV.empty?
  warn "Usage: #{File.basename($PROGRAM_NAME)} HAR_FILE [HAR_FILE ...]"
  exit 64
end

har_paths = ARGV
entries = []
api_entries = []
har_inventory = []

har_paths.each do |path|
  har = JSON.parse(File.read(path))
  source_entries = har.fetch("log").fetch("entries")
  har_inventory << {
    "file" => File.basename(path),
    "path" => path,
    "entries" => source_entries.length,
    "base64_entries" => source_entries.count { |entry| entry.dig("response", "content", "encoding") == "base64" }
  }
  source_entries.each_with_index do |entry, index|
    source = decode_response(entry)
    next if source.nil?
    url = entry.dig("request", "url").to_s
    mime = entry.dig("response", "content", "mimeType").to_s
    entries << [File.basename(path), index, url, source] if url.match?(%r{/(?:promotionark|ark-app-root|jarvis|datacenterark)/}) && mime.match?(/javascript|text\/javascript/)
    api_entries << [File.basename(path), index, url, source] if schema_safe_endpoint?(url) && mime.match?(/json|text\/json/)
  end
end

seen_assets = {}
rows = []

entries.each do |har_file, entry_index, url, source|
  source_hash = Digest::SHA256.hexdigest(source)
  next if seen_assets.key?(source_hash)
  seen_assets[source_hash] = true

  properties = extract_properties(source)
  properties.each_with_index do |(_position, property_key, explanation), property_index|
    next unless EXPLANATION_KEYS.include?(property_key)
    explanation = strip_markup(explanation).gsub(/\\[nrt]/, " ").strip
    next unless explanation.match?(/[\p{Han}]/) && explanation.length >= 2

    window_start = [property_index - 20, 0].max
    window_end = [property_index + 20, properties.length - 1].min
    labels = properties[window_start..window_end]
      .select { |_position, key, value| LABEL_KEYS.include?(key) && value.match?(/[\p{Han}]/) }
      .map { |_position, _key, value| strip_markup(value).strip }
      .reject { |value| value.empty? || value == explanation }
      .uniq
    next if labels.empty?

    labels.each do |field|
      rows << {
        "field" => field,
        "explanation" => explanation,
        "classification" => classify(field, explanation, property_key),
        "confidence" => confidence(property_key, url),
        "source_key" => property_key,
        "source_asset" => url.split("/").last.split("?").first,
        "source_har" => har_file,
        "har_entry" => entry_index,
        "source_url" => url
      }
    end
  end
end

rows = rows.uniq { |row| row.values_at("field", "explanation", "source_url", "source_key") }
deduped = rows.group_by { |row| row.values_at("field", "explanation") }.map do |(field, explanation), grouped|
  grouped.first.merge(
    "source_asset" => grouped.map { |row| row["source_asset"] }.uniq.join("; "),
    "source_har" => grouped.map { |row| row["source_har"] }.uniq.join("; "),
    "har_entry" => grouped.map { |row| "#{row["source_har"]}:#{row["har_entry"]}" }.uniq.join("; "),
    "source_url" => grouped.map { |row| row["source_url"] }.uniq.join("; "),
    "source_key" => grouped.map { |row| row["source_key"] }.uniq.join("; "),
    "confidence" => grouped.map { |row| row["confidence"] }.include?("high") ? "high" : grouped.first["confidence"]
  )
end.sort_by { |row| [row["classification"], row["field"], row["explanation"]] }

api_metrics = []
schema_paths = Hash.new { |hash, key| hash[key] = { "count" => 0, "types" => Hash.new(0), "source_har" => Set.new, "har_entry" => Set.new, "source_url" => Set.new } }
api_entries.each do |source|
  json = JSON.parse(source[3]) rescue nil
  next unless json
  collect_api_metrics(json, source, api_metrics)
  paths = []
  collect_schema(json, "", paths)
  paths.each do |path, field, type|
    key = [source[2].split("?").first, path]
    schema_paths[key]["count"] += 1
    schema_paths[key]["types"][type] += 1
    schema_paths[key]["source_har"] << source[0]
    schema_paths[key]["har_entry"] << source[1]
    schema_paths[key]["source_url"] << source[2].split("?").first
    schema_paths[key]["field"] = field
    schema_paths[key]["path"] = path
  end
end

api_metrics = api_metrics.uniq { |row| row.values_at("field", "explanation", "metric_id", "source_url") }
api_metrics = api_metrics.group_by { |row| [row["metric_id"] || row["field"], row["explanation"]] }.map do |(_key, grouped)|
  grouped.first.merge(
    "modules" => grouped.map { |row| row["modules"] }.reject(&:empty?).uniq.join("; "),
    "source_har" => grouped.map { |row| row["source_har"] }.uniq.join("; "),
    "har_entry" => grouped.map { |row| "#{row["source_har"]}:#{row["har_entry"]}" }.uniq.join("; "),
    "source_url" => grouped.map { |row| row["source_url"] }.uniq.join("; ")
  )
end.sort_by { |row| [row["field"], row["explanation"]] }
schema_rows = schema_paths.values.map do |row|
  {
    "endpoint" => row["source_url"].first,
    "field" => row["field"],
    "json_path" => row["path"],
    "observed_types" => row["types"].keys.join("; "),
    "response_occurrences" => row["count"],
    "source_har" => row["source_har"].to_a.join("; "),
    "har_entry" => row["har_entry"].to_a.sort.join("; ")
  }
end.sort_by { |row| [row["endpoint"], row["json_path"]] }

FileUtils.mkdir_p(OUTPUT_DIR)
headers = %w[field explanation classification confidence source_key source_asset source_har har_entry source_url]
[
  ["xiaohongshu-har-field-candidates.csv", rows],
  ["xiaohongshu-field-dictionary.csv", deduped],
  ["xiaohongshu-field-dictionary-useful.csv", deduped.reject { |row| row["classification"] == "ordinary_prompt" }],
  ["xiaohongshu-field-dictionary-core.csv", deduped.reject { |row| %w[ordinary_prompt campaign_rule_or_example].include?(row["classification"]) }]
].each do |filename, data|
  CSV.open(File.join(OUTPUT_DIR, filename), "wb", write_headers: true, headers: headers) do |csv|
    data.each { |row| csv << headers.map { |header| row[header] } }
  end
end

metric_headers = %w[field explanation classification confidence source_key metric_id modules online source_har har_entry source_url]
CSV.open(File.join(OUTPUT_DIR, "xiaohongshu-api-metric-dictionary.csv"), "wb", write_headers: true, headers: metric_headers) do |csv|
  api_metrics.each { |row| csv << metric_headers.map { |header| row[header] } }
end

schema_headers = %w[endpoint field json_path observed_types response_occurrences source_har har_entry]
CSV.open(File.join(OUTPUT_DIR, "xiaohongshu-api-schema.csv"), "wb", write_headers: true, headers: schema_headers) do |csv|
  schema_rows.each { |row| csv << schema_headers.map { |header| row[header] } }
end

metadata = {
  "har_inventory" => har_inventory,
  "scope" => "已加载的静态资源中的字段/指标/选项解释候选；不等同于整个站点所有页面的运行时可见字段",
  "unique_decoded_assets" => seen_assets.length,
  "candidate_row_count" => rows.length,
  "deduped_field_count" => deduped.length,
  "useful_field_count" => deduped.count { |row| row["classification"] != "ordinary_prompt" },
  "core_field_count" => deduped.count { |row| !%w[ordinary_prompt campaign_rule_or_example].include?(row["classification"]) },
  "api_metric_count" => api_metrics.length,
  "api_schema_path_count" => schema_rows.length,
  "classification_counts" => deduped.group_by { |row| row["classification"] }.transform_values(&:length),
  "confidence_counts" => deduped.group_by { |row| row["confidence"] }.transform_values(&:length)
}
File.write(File.join(OUTPUT_DIR, "xiaohongshu-field-dictionary-metadata.json"), JSON.pretty_generate(metadata) + "\n")
puts JSON.generate(metadata)
