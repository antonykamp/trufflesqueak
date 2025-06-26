import argparse
import re
import logging
import csv
from pathlib import Path

logger = logging.getLogger()
logger.setLevel(logging.DEBUG) # base loglevel needed

argparser = argparse.ArgumentParser(description='''
    Tool to analyze differences between two TruffleSqueak compilation trace logs.
    For example, you could analyze two log files containing the compilation traces while executing the AWFYJson benchmark.
''')
argparser.add_argument('log_file_compare_base', help='Path to the compilation log file which acts as the comparison base.')
argparser.add_argument('log_file_compare_target', help='Path to the compilation log file to compare to the first one.')
argparser.add_argument('-o', '--outputDir', help='''
    Optional path to an output directory. Any content in previously dumped files is overwritten.
    If not present, then stdout is used for log output and the directory of this script is used for file outputs.'
''')
argparser.add_argument('-m', '--metric', choices=['AST_size', 'code_size', 'inlining', 'compilation_time'], help='''
    Optional specification of a special metric that results in a file that explicitly sorts methods by the metric.
''')
argparser.add_argument('-p', '--positional_shifts', action='store_true', help='''
    Optional flag which enables analysis of positional shifts of methods between traces.
    Beware that positions are influenced by whether compilation takes place in only the main thread/multiple threads are used.
''')
argparser.add_argument('-s', '--summary', action='store_true', help='''
    Optional flag which enables analysis of summary statistics between traces.
''')

args = argparser.parse_args()

if args.outputDir is not None:
    # Create logfile in given output directory to log results
    fh = logging.FileHandler(args.outputDir + '/analysis.log', 'w+')
    fh.setLevel(logging.INFO)
    logger.addHandler(fh)
else:
    # Use STDOUT for logging
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    logger.addHandler(ch)

def read_trace_lines(filename):
    # Possible lines used for deveopment and testing based on https://gist.github.com/TruffleSqueak-Bot/de67fec8ff3dc0b56837e30c85b88d94.
    # [engine] opt done   engine=1  id=613   AWFYJsonParser>>#startCapture                      |Tier 1|Time    10(   6+4   )ms|AST   17|Inlined   0Y   0N|IR    183/   219|CodeSize     767|Addr 0x7f071eaf3000|UTC 2025-05-18T08:07:25.292|Src n/a
    # [engine] opt inval. engine=1  id=629   AWFYVector>>#append:                                                                                                                                               |UTC 2025-05-18T08:07:25.241|Src n/a|Reason null
    # [engine] opt deopt  engine=1  id=629   AWFYVector>>#append:                               |                                                                                                               |UTC 2025-05-18T08:07:25.241|Src n/a
    return [ line for line in open(filename) if line.startswith('[engine]') and 'statistics' not in line and 'CodeAddress' not in line]

def read_and_parse_total_compilation_count(filename):
    #     Compilations                : 185
    matching =  [line for line in open(filename) if line.strip().startswith('Compilations')]
    if len(matching) == 0 or len(matching) > 1:
        logger.error("Matched no or too many lines for total Compilations")
        raise ValueError
    re_match = re.search(r'Compilations\s+:\s+(\d+)', matching[0])
    if re_match:
        return int(re_match.group(1))
    return None

def read_and_parse_node_summary(filename):
    #     Truffle node count          : count= 183, sum=     98687, min=      11, average=      539.27, max=    5574, maxTarget=AWFYBenchmark>>#innerBenchmarkLoop:
    matching =  [line for line in open(filename) if 'Truffle node count' in line]
    if len(matching) == 0 or len(matching) > 1:
        logger.error("Matched no or too many Truffle node count lines")
        raise ValueError

    result = {}
    re_match = re.search(r'sum=\s+(\d+),\s+min=\s+(\d+),\s+average=\s+(\d+\.\d+),\s+max=\s+(\d+)', matching[0])
    if re_match:
        result["sum"] = int(re_match.group(1))
        result["min"] = int(re_match.group(2))
        result["average"] = float(re_match.group(3))
        result["max"] = int(re_match.group(4))
    return result

def read_and_parse_compilation_statistics(filename):
    # Compilation Tier 1          :
    #    [...]
    #    Time for compilation (us)   : count= 119, sum=   1526184, min=    2310, average=    12825.08, max=  103281, maxTarget=AWFYJsonParser>>#readValue
    #      [...]
    #    [...]
    #      Code size                 : count= 116, sum=    303260, min=     508, average=     2614.31, max=   18620, maxTarget=AWFYJsonParser>>#readValue
    compilation_tier_lines =  [line for line in open(filename) if 'Compilation Tier' in line]
    compilation_time_lines =  [line for line in open(filename) if 'Time for compilation (us)' in line]
    code_size_lines =  [line for line in open(filename) if 'Code size' in line]

    # Need for tier-specific parsing and sometimes e.g. only tier 2 compilation is present
    tier_count = len(compilation_tier_lines)
    result = {}
    for i in range(0, tier_count):
        result_for_tier = {}
        compilation_time_match_for_tier = re.search(r'sum=\s+(\d+),\s+min=\s+(\d+),\s+average=\s+(\d+\.\d+),\s+max=\s+(\d+)', compilation_time_lines[i])
        if compilation_time_match_for_tier:
            result_for_tier["compilation_time_sum"] = int(compilation_time_match_for_tier.group(1))
            result_for_tier["compilation_time_min"] = int(compilation_time_match_for_tier.group(2))
            result_for_tier["compilation_time_average"] = float(compilation_time_match_for_tier.group(3))
            result_for_tier["compilation_time_max"] = int(compilation_time_match_for_tier.group(4))

        code_size_match_for_tier = re.search(r'sum=\s+(\d+),\s+min=\s+(\d+),\s+average=\s+(\d+\.\d+),\s+max=\s+(\d+)', code_size_lines[i])
        if code_size_match_for_tier:
            result_for_tier["code_size_sum"] = int(code_size_match_for_tier.group(1))
            result_for_tier["code_size_min"] = int(code_size_match_for_tier.group(2))
            result_for_tier["code_size_average"] = float(code_size_match_for_tier.group(3))
            result_for_tier["code_size_max"] = int(code_size_match_for_tier.group(4))

        tier = i + 1
        result[tier] = result_for_tier

    return result

# Analyze diffs of summary statistics and output as csv
if args.summary:
    node_summary_1 = read_and_parse_node_summary(args.log_file_compare_base)
    node_summary_2 = read_and_parse_node_summary(args.log_file_compare_target)

    total_compilation_count_1 = read_and_parse_total_compilation_count(args.log_file_compare_base)
    total_compilation_count_2 = read_and_parse_total_compilation_count(args.log_file_compare_target)

    compilation_summary_1 = read_and_parse_compilation_statistics(args.log_file_compare_base)
    compilation_summary_2 = read_and_parse_compilation_statistics(args.log_file_compare_target)

    # OUTPUT AS CSV
    summary_diffs_output_path = args.outputDir + "/summary_diffs.csv" if args.outputDir is not None else "summary_diffs.csv"
    with open(summary_diffs_output_path, 'w+', newline='') as summary_diffs_csv_file:
        writer = csv.writer(summary_diffs_csv_file)
        # Header
        writer.writerow(['metric', 'value_in_base_file', 'value_in_target_file','diff'])
        # Rows
        writer.writerow(['total_compilation_count', total_compilation_count_1, total_compilation_count_2, total_compilation_count_2 - total_compilation_count_1])
        writer.writerow(['AST_size_sum', node_summary_1["sum"], node_summary_2["sum"], node_summary_2["sum"] - node_summary_1["sum"]])

        # Assume possible tiers are 1 and 2.
        for tier in range(1, 3):
            tier_present_in_1 = tier in list(compilation_summary_1.keys())
            tier_present_in_2 = tier in list(compilation_summary_2.keys())

            if tier_present_in_1 is False or tier_present_in_2 is False:
                # Tier not present in one of traces -> skip comparison
                continue
            for metric in list(compilation_summary_1[tier].keys()):
                writer.writerow([f'{metric} (tier {tier})', compilation_summary_1[tier][metric], compilation_summary_2[tier][metric], compilation_summary_2[tier][metric] - compilation_summary_1[tier][metric] ])
else:
    logger.info("# Analysis of summary statistics skipped")

#####

def parse_trace_line(line):
    result = {}

    # Extract ID and method
    id_method_match = re.search(r'id=(\d+)\s+([^\|]+)', line)
    if id_method_match:
        result["id"] = int(id_method_match.group(1))
        result["method"] = id_method_match.group(2).strip()

    # Extract and normalize compilation_state
    state_match = re.search(r'\[engine\]\s+opt\s+(done|inval\.|deopt)', line)
    if state_match:
        raw_state = state_match.group(1)
        normalized_state = {
            "done": "compiled",
            "inval.": "invalidated",
            "deopt": "deoptimized"
        }.get(raw_state, raw_state)
        result["compilation_state"] = normalized_state

    # Extract compilation tier
    tier_match = re.search(r'\|Tier (\d+)\|', line)
    if tier_match:
        result["compilation_tier"] = int(tier_match.group(1))

    # Extract compilation time
    time_match = re.search(r'Time\s+(\d+)\(', line)
    if time_match:
        result["compilation_time_total"] = int(time_match.group(1).strip())

    # Extract code size
    code_size_match = re.search(r'CodeSize\s+(\d+)', line)
    if code_size_match:
        result["code_size"] = int(code_size_match.group(1))
        
    # Extract AST size
    AST_size_match = re.search(r'AST\s+(\d+)', line)
    if code_size_match:
        result["AST_size"] = int(AST_size_match.group(1))
        
    # Extract inlining information of other methods that were called from the current method
    inlining_match = re.search(r'Inlined\s+(\d+)Y\s+(\d+)N', line)
    if inlining_match:
        result["inlined_method_calls"] = int(inlining_match.group(1))
        result["not_inlined_method_calls"] = int(inlining_match.group(2))
        result["method_calls"] = int(inlining_match.group(1)) + int(inlining_match.group(2))
    return result

trace_log_1 = list(map(parse_trace_line, read_trace_lines(args.log_file_compare_base)))
trace_log_2 = list(map(parse_trace_line, read_trace_lines(args.log_file_compare_target)))

#####

# Find all method entries that indicate successful compilation
compiled_methods_1 = [method for method in trace_log_1 if method["compilation_state"] == "compiled"]
compiled_methods_2 = [method for method in trace_log_2 if method["compilation_state"] == "compiled"]

# Find all methods entries that indicate invalidation at some point of time
invalidated_methods_1 = [method for method in trace_log_1 if method["compilation_state"] == "invalidated"]
invalidated_methods_2 = [method for method in trace_log_2 if method["compilation_state"] == "invalidated"]

# Indicate new methods getting compiled
new_compiled_methods = [method for method in compiled_methods_2 if method["method"] not in list(map(lambda method: method["method"], compiled_methods_1))]

# Indicate methods no longer getting compiled
no_longer_compiled = [method for method in compiled_methods_1 if method["method"] not in list(map(lambda method: method["method"], compiled_methods_2))]

#####

# Indicate shift in compilation trace (+ / - x positions) (without invalidations and deopts)
# and also report/log on newly compiled/no longer compiled methods.

if args.positional_shifts:
    shift_list=[]
    logger.info("# Positional shifts in compilation traces\n")
    seen_indexes_in_2 = {}
    for index_1, method in enumerate(compiled_methods_1):
      if method["method"] in list(map(lambda method: method["method"], no_longer_compiled)):
        logger.info("---")
        logger.info(method["method"])
        logger.info("is no longer compiled in the second trace")
        continue
      if method["method"] in list(map(lambda method: method["method"], new_compiled_methods)):
        logger.info("---")
        logger.info(method["method"])
        logger.info("is a new compilation target in the second trace")
        continue

      seen_indexes_in_2_for_method = seen_indexes_in_2[method["method"]] if method["method"] in seen_indexes_in_2 else []
      # Use the last seen index_2
      start = seen_indexes_in_2_for_method[-1 ] if len(seen_indexes_in_2_for_method) > 0 else -1
      try:
        index_2 = list(map(lambda method: method["method"], compiled_methods_2)).index(method["method"], start + 1)
      except ValueError:
        continue
      # Mark this index in 2 as seen in order to avoid false comparisons of e.g. the second occurence in trace 1 with the first in trace 2
      seen_indexes_in_2_for_method.append(index_2)
      seen_indexes_in_2[method["method"]] = seen_indexes_in_2_for_method

      shift = index_1 - index_2
      if shift != 0:
        logger.info("---")
        logger.info(method["method"])
        logger.info("Compilation occurrence: " + str(len(seen_indexes_in_2_for_method)) + ".")
        logger.info("Compilation tier: " + str(method["compilation_tier"]))
        logger.info("Positional shift: " + str(shift))
        
        # Store for csv writing
        shift_list.append({ 
          "method_name": method["method"],
          "compilation_occurence": str(len(seen_indexes_in_2_for_method)) + ".",
          "compilation_tier": method["compilation_tier"],
          "positional_shift": shift,
        })

    # OUTPUT AS CSV
    shifts_output_path = args.outputDir + "/shifts.csv" if args.outputDir is not None else "shifts.csv"
    with open(shifts_output_path, 'w+', newline='') as shifts_csv_file:
        writer = csv.writer(shifts_csv_file)
        writer.writerow(['method_name', 'compilation_occurence', 'compilation_tier','positional_shift'])
        for method in shift_list:
            writer.writerow([method["method_name"], method["compilation_occurence"], method["compilation_tier"], method["positional_shift"]])
else:
    logger.info("# Analysis of positional shifts skipped")

#####

# Further split compiled methods by compilation tier
compiled_methods_1_tier_1 = [method for method in compiled_methods_1 if method["compilation_tier"] == 1]
compiled_methods_1_tier_2 = [method for method in compiled_methods_1 if method["compilation_tier"] == 2]

compiled_methods_2_tier_1 = [method for method in compiled_methods_2 if method["compilation_tier"] == 1]
compiled_methods_2_tier_2 = [method for method in compiled_methods_2 if method["compilation_tier"] == 2]

# Analyze diffs between traces by compilation tier

diff_list = []
def analyze_diffs(methods_from_1, methods_from_2):
    occurences_dict = {}
    for method_1 in methods_from_1:
      occurences_for_method = (occurences_dict[method_1["method"]] if method_1["method"] in occurences_dict else 0) + 1
      occurences_dict[method_1["method"]] = occurences_for_method

      if method_1["method"] in list(map(lambda method : method["method"], methods_from_2)):
        method_2 = None
        iter_in_2 = (method_2 for method_2 in methods_from_2 if method_2["method"] == method_1["method"])
        for i in range(0, occurences_for_method):
          method_2 = next(iter_in_2, None)
          
        if method_2 is None:
            # There is no matching occurence of the method in the second trace anymore.
            # (it occurs in the first trace more often than in the second trace in the specified tier)
            logger.info("---")
            logger.info(method_1["method"])
            logger.info("Compilation occurence: " + str(occurences_for_method) + ".")
            logger.info("Compilation tier: " + str(method_1["compilation_tier"]))
            logger.info("was not found anymore in the second trace")
            continue

        code_size_diff = method_2["code_size"] - method_1["code_size"]
        compilation_time_diff = method_2["compilation_time_total"] - method_1["compilation_time_total"]
        AST_size_diff = method_2["AST_size"] - method_1["AST_size"]
        inlined_diff = method_2["inlined_method_calls"] - method_1["inlined_method_calls"]
        not_inlined_diff = method_2["not_inlined_method_calls"] - method_1["not_inlined_method_calls"]

        if code_size_diff != 0 or compilation_time_diff != 0 or AST_size_diff != 0 or inlined_diff != 0 or not_inlined_diff != 0:
          logger.info("---")
          logger.info(method_1["method"])
          logger.info("Compilation occurence: " + str(occurences_for_method) + ".")
          logger.info("Compilation tier: " + str(method_1["compilation_tier"]))
          
          # Store for csv writing
          diff_list.append({ 
            "method_name": method_1["method"],
            "compilation_occurence": str(occurences_for_method) + ".",
            "compilation_tier": method_1["compilation_tier"],
            "code_size_diff": code_size_diff,
            "AST_size_diff": AST_size_diff,
            "inlined_diff": inlined_diff,
            "not_inlined_diff": not_inlined_diff,
            "compilation_time_diff": compilation_time_diff,
          })
        if code_size_diff != 0:
          logger.info("Code size difference: " + str(code_size_diff))
        if AST_size_diff != 0:
          logger.info("AST size difference: " + str(AST_size_diff))
        if inlined_diff != 0:
          logger.info("Difference in amount of inlined methods: " + str(inlined_diff))
        if not_inlined_diff != 0:
          logger.info("Difference in amount of not inlined methods: " + str(not_inlined_diff))
        if compilation_time_diff != 0:
          logger.info("Compilation time difference: " + str(compilation_time_diff) + "ms")
      else:
        logger.info("---")
        logger.info(method_1["method"])
        logger.info("Compilation occurence: " + str(occurences_for_method) + ".")
        logger.info("Compilation tier: " + str(method_1["compilation_tier"]))
        logger.info("is no longer compiled in this tier")
                
logger.info("\n# Diffs in metrics (Tier 1)\n")
analyze_diffs(compiled_methods_1_tier_1, compiled_methods_2_tier_1)
logger.info("\n# Diffs in metrics (Tier 2)\n")
analyze_diffs(compiled_methods_1_tier_2, compiled_methods_2_tier_2)
    
# OUTPUT AS CSV (all diffs)
diffs_output_path = args.outputDir + "/diffs.csv" if args.outputDir is not None else "diffs.csv"
with open(diffs_output_path, 'w+', newline='') as diff_csv_file:
    writer = csv.writer(diff_csv_file)
    writer.writerow(['method_name', 'compilation_occurence', 'compilation_tier','code_size_diff','AST_size_diff','inlined_diff','not_inlined_diff','compilation_time_diff'])
    for method in diff_list:
        writer.writerow([method["method_name"], method["compilation_occurence"], method["compilation_tier"], method["code_size_diff"], method["AST_size_diff"], method["inlined_diff"], method["not_inlined_diff"], method["compilation_time_diff"]])

# OUTPUT AS CSV (based on specified metric)
relevant_metric_columns=[] 
if args.metric is not None:
    specific_diff_list = []
    if args.metric == 'AST_size':
        relevant_metric_columns.append('AST_size_diff')
        filtered_diff_list = [method_diff for method_diff in diff_list if method_diff['AST_size_diff'] != 0]
        specific_diff_list = sorted(filtered_diff_list, key=lambda method_diff : method_diff['AST_size_diff'])
    elif args.metric == 'code_size':
        relevant_metric_columns.append('code_size_diff')
        filtered_diff_list = [method_diff for method_diff in diff_list if method_diff['code_size_diff'] != 0]
        specific_diff_list = sorted(filtered_diff_list, key=lambda method_diff : method_diff['code_size_diff'])
    elif args.metric == 'compilation_time':
        relevant_metric_columns.append('compilation_time_diff')
        filtered_diff_list = [method_diff for method_diff in diff_list if method_diff['compilation_time_diff'] != 0]
        specific_diff_list = sorted(filtered_diff_list, key=lambda method_diff : method_diff['compilation_time_diff'])
    elif args.metric == 'inlining':
        relevant_metric_columns.append('inlined_diff')
        relevant_metric_columns.append('not_inlined_diff')
        filtered_diff_list = [method_diff for method_diff in diff_list if method_diff['inlined_diff'] != 0 or method_diff['not_inlined_diff'] != 0]
        specific_diff_list = sorted(filtered_diff_list, key=lambda method_diff : (method_diff['inlined_diff'], method_diff['not_inlined_diff']))

    common_csv_columns = ['method_name', 'compilation_occurence', 'compilation_tier']
    diffs_output_path = args.outputDir + f"/diffs_{args.metric}.csv" if args.outputDir is not None else f"diffs_{args.metric}.csv"
    with open(diffs_output_path, 'w+', newline='') as diff_csv_file:
        writer = csv.writer(diff_csv_file)
        writer.writerow(common_csv_columns + [column for column in relevant_metric_columns])
        for method in specific_diff_list:
            writer.writerow([method[column] for column in common_csv_columns] + [method[column] for column in relevant_metric_columns])

#####

# Visualize metric diffs by coloring in target log file and outputting it as html.

compiled_methods_tier_1_count = {}
compiled_methods_tier_2_count = {}

def get_color(line):
    method = parse_trace_line(line)
    default = "white"  # default background
    
    if not (line.startswith('[engine]') and 'statistics' not in line and 'CodeAddress' not in line):
        # No relevant line overall
        return default

    if method["compilation_state"] != "compiled":
        # Only look for actual compilations (no deopts or invalidations
        return default 
    
    if method["method"] not in list(map(lambda method_diff : method_diff["method_name"], diff_list)):
        # No diffs at all --> no special color
        return default
        
    # While reading in line by line for coloring, we need to keep track of the occurence count (relative to tier).
    # Only this way, we can correctly color the rows based on their diffs.
    occurence_of_method_relative_to_tier = None
    if method["compilation_tier"] == 1:
        occurences_for_method = (compiled_methods_tier_1_count[method["method"]] if method["method"] in compiled_methods_tier_1_count else 0) + 1
        compiled_methods_tier_1_count[method["method"]] = occurences_for_method
    elif method["compilation_tier"] == 2:
        occurences_for_method = (compiled_methods_tier_2_count[method["method"]] if method["method"] in compiled_methods_tier_2_count else 0) + 1
        compiled_methods_tier_2_count[method["method"]] = occurences_for_method
       
    match_in_diff_list = next((x for x in diff_list if x["compilation_tier"] == method["compilation_tier"] and x["method_name"] == method["method"] and x["compilation_occurence"] == (str(occurences_for_method) + ".")), None)
    
    if match_in_diff_list == None:
        # No match 
        return default

    if len(relevant_metric_columns) == 1:
        # only one relevant column
        if match_in_diff_list[relevant_metric_columns[0]] < 0:
            # Decrease in metric interpreted as good
            return "lightgreen"
        elif match_in_diff_list[relevant_metric_columns[0]] > 0:
            # Increase in metric interpreted as bad
            return "orangered"
        else:
            return default
    elif len(relevant_metric_columns) == 2:
        if match_in_diff_list[relevant_metric_columns[0]] == 0 and match_in_diff_list[relevant_metric_columns[1]] == 0:
            # both columns of metric unchanged => no color
            return default
        else:
            # In any other case just highlight the line, but interpretation is not possible (good or bad)
            return "lightgrey"
    else:
        return default

    # OUTDATED COLORING BASED ON CODE_SIZE & COMPILATION_TIME
    
    # if match_in_diff_list == None:
        # # No match 
        # return default
    # elif match_in_diff_list["code_size_diff"] < 0 and match_in_diff_list["compilation_time_diff"] < 0:
        # # Decrease in both metrics => the best case
        # return "green"
    # elif (match_in_diff_list["code_size_diff"] < 0 and match_in_diff_list["compilation_time_diff"] == 0) or (match_in_diff_list["code_size_diff"] == 0 and match_in_diff_list["compilation_time_diff"] < 0):
        # # Decrease in one metric while the other stayed consistent, good but it could be better :D
        # return "lightgreen"
        # #return default
    # elif (match_in_diff_list["code_size_diff"] > 0 and match_in_diff_list["compilation_time_diff"] < 0) or (match_in_diff_list["code_size_diff"] < 0 and match_in_diff_list["compilation_time_diff"] > 0):
        # # Mixed signals as one metric increased, one decreased.
        # return "khaki"
        # #return default
    # elif (match_in_diff_list["code_size_diff"] > 0 and match_in_diff_list["compilation_time_diff"] == 0) or (match_in_diff_list["code_size_diff"] == 0 and match_in_diff_list["compilation_time_diff"] > 0):
        # # Increase in one metric while the other stayed consistent, bad but not that it could be worse :D
        # return "lightsalmon"
        # #return default
    # elif match_in_diff_list["code_size_diff"] > 0 and match_in_diff_list["compilation_time_diff"] > 0:
        # # Increase in both metrics => worst case
        # return "red"
    # else:
        # return default
        
def get_font_weight(line):
    method = parse_trace_line(line)
    default = "normal"  # default font weight
    
    if not (line.startswith('[engine]') and 'statistics' not in line and 'CodeAddress' not in line):
        # No relevant line overall
        return default

    if method["compilation_state"] != "compiled":
        # Only look for actual compilations (no deopts or invalidations)
        return default 
    
    if method["method"] not in list(map(lambda method : method["method"], new_compiled_methods)):
        # No new method -> normal font weight
        return default   

    # New method -> mark as bold
    return "bold"
        
def line_to_html(line):
    color = get_color(line)
    font_weight = get_font_weight(line)
    # Escape HTML special characters if needed
    safe_line = re.sub('(?<!>)>', '&gt;', line.replace("&", "&amp;").replace("<", "&lt;"))
    # Special handling for ">" as Squeak method names contain ">>"
    return f'<div style="background-color:{color}; font-weight: {font_weight}; font-family: monospace; width: max-content;white-space: pre;">{safe_line}</div>'

def convert_new_log_to_html(log_path, output_path):
    with open(log_path, "r") as f:
        lines = f.readlines()

    html_lines = [line_to_html(line) for line in lines]

    html_content = (
        f"<html lang='en'><head><title>Target compilation trace colored by {args.metric}</title></head><body>\n"
        + "\n".join(html_lines) +
        "\n</body></html>"
    )

    with open(output_path, "w+") as f:
        f.write(html_content)

if args.metric is not None:
   output_path = args.outputDir + f'/target_log_colored_by_{args.metric}.html' if args.outputDir is not None else f'target_log_colored_by_{args.metric}.html'
   convert_new_log_to_html(args.log_file_compare_target, output_path)
else:
   logger.info("\n # Colorization of target logfile skipped as no metric was specified\n")