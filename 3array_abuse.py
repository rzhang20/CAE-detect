import os
import re
import csv
from collections import defaultdict

def is_code_file(filename):
    return filename.endswith(('.cpp', '.cc', '.c', '.h', '.hpp'))

def extract_static_arrays(code):
    # 返回 [(变量名, 下标名)]
    pattern = re.compile(
        r'\b(?:int|float|double|char|bool|unsigned|long|short)\s+(\w+)\s*\[\s*(\w+)\s*\]\s*[;=]')
    return pattern.findall(code)

def extract_static_template_types(code):
    # 提取静态数组中的模板类型，比如 std::array<Point<dim>, ...>
    pattern = re.compile(r'std::array\s*<\s*([a-zA-Z_:<>0-9]+)\s*,')
    return pattern.findall(code)

def extract_dynamic_template_types(code):
    # 提取动态数组中模板类型，比如 std::vector<Point<dim>>
    pattern = re.compile(r'std::vector\s*<\s*([a-zA-Z_:<>0-9]+)\s*>')
    return pattern.findall(code)

def detect_static_arrays(code):
    patterns = [
        r'\b(?:int|float|double|char|bool|unsigned|long|short)\s+\w+\s*\[[^\]]+\]\s*[;=]',
        r'\bstd::array<.+?>\s+\w+\s*[;=]',
        r'\b\w+\s+\w+\s*\[\s*GeometryInfo<[^>]+>::vertices_per_cell\s*\]\s*[;=]',
        r'\bstd::array<.+?>\s+\w+\s*\([^)]*\)\s*(const)?\s*(override)?\s*;',
        r'std::fill\s*\(\s*std::begin\s*\(\s*\w+\s*\)\s*,\s*std::end\s*\(\s*\w+\s*\)\s*,'
    ]
    return sum(len(re.findall(p, code)) for p in patterns)

def detect_dynamic_arrays(code):
    patterns = [
        r'\bstd::vector<[^>]+>\s+(\w+)',
        r'\bboost::container::small_vector<[^>]+>\s+(\w+)',
        r'new\s+\w+\s*\[(\w+)\]'
    ]
    dynamic_vars = set()
    for pattern in patterns:
        dynamic_vars.update(re.findall(pattern, code))
    return dynamic_vars

def collect_code_files(root_path):
    code_files = []
    for folder, _, files in os.walk(root_path):
        for file in files:
            if is_code_file(file):
                code_files.append(os.path.join(folder, file))
    return code_files

def analyze_directory(root_path, output_csv_path):
    code_files = collect_code_files(root_path)
    results = []
    static_info = defaultdict(list)
    file_static_counts = {}
    file_dynamic_counts = {}
    file_static_templates = defaultdict(set)
    file_dynamic_templates = defaultdict(set)

    for file_path in code_files:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                code = f.read()
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            continue

        statics = extract_static_arrays(code)
        static_count = detect_static_arrays(code)
        dynamic_vars = detect_dynamic_arrays(code)
        dynamic_count = len(dynamic_vars)
        total = static_count + dynamic_count
        static_ratio = (static_count / total) if total > 0 else 0

        # 提取模板类型
        static_templates = set(extract_static_template_types(code))
        dynamic_templates = set(extract_dynamic_template_types(code))

        file_static_counts[file_path] = (static_count, dynamic_count, static_ratio)
        static_info[file_path] = statics
        file_dynamic_counts[file_path] = dynamic_vars
        file_static_templates[file_path] = static_templates
        file_dynamic_templates[file_path] = dynamic_templates

    # 判断每个文件是否存在数组滥用
    for file_path in code_files:
        static_count, dynamic_count, static_ratio = file_static_counts[file_path]
        statics = static_info[file_path]
        abuse = "否"

        if 0 < static_ratio < 1.0:
            abuse = "是"
        elif static_ratio == 1.0:
            suspected_vars = set(var for pair in statics for var in pair)
            conflict_found = False

            # 检查变量名是否在其他文件中作为动态数组使用
            for other_path, dyn_vars in file_dynamic_counts.items():
                if other_path != file_path and (suspected_vars & dyn_vars):
                    conflict_found = True
                    break

            # 检查模板类型是否存在动态数组形式
            if not conflict_found:
                static_types = file_static_templates[file_path]
                for other_path, dyn_templates in file_dynamic_templates.items():
                    if other_path == file_path:
                        continue
                    for t in static_types:
                        if t in dyn_templates:
                            conflict_found = True
                            break
                    if conflict_found:
                        break

            abuse = "是" if conflict_found else "否"

        results.append([
            file_path, static_count, dynamic_count,
            f"{static_ratio * 100:.1f}%", abuse
        ])

    with open(output_csv_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["文件名", "静态数组数", "动态数组数", "静态占比（%）", "数组滥用"])
        writer.writerows(results)

    print(f"分析完成，结果已保存到：{output_csv_path}")

# 设置路径
input_dir = r"C:\Users\dell\Desktop\检测的CAE项目\8dealii-11-27"
output_csv = os.path.join(input_dir, "array_abuse_analysis.csv")
analyze_directory(input_dir, output_csv)
