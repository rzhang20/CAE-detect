import os
import re
import csv
from collections import defaultdict

FORTRAN_EXTENSIONS = {'.f', '.f90', '.f95', '.for'}

# 通用模式定义
double_precision_decl = re.compile(r'\bdouble\s+precision\b\s+([\w,\s*()]+)', re.IGNORECASE)
double_constant = re.compile(r'\d+\.\d*d[0-9+\-]+', re.IGNORECASE)
assignment_pattern = re.compile(r'(\w+)\s*=\s*([^!]+)')  # lhs = rhs
real_decl_pattern = re.compile(r'\breal\s*\(([^)]+)\)', re.IGNORECASE)
real_variable_pattern = re.compile(r'\breal\s*\(.*?\).*::\s*(.*)', re.IGNORECASE)
float_t_pattern = re.compile(r'\bfloat_t\b', re.IGNORECASE)

# 可识别的布尔值字符串（可扩展）
boolean_like_values = {'0', '1', '0.0', '1.0', '0d0', '1d0', 'zero', 'one'}

def is_simple_assignment(rhs: str) -> bool:
    if any(op in rhs for op in ['**', '/', 'sqrt', 'exp', 'log']):
        return False
    return True

def normalize_value(val: str) -> str:
    """标准化右值（去除括号、空格、大小写），便于判断是否为布尔值"""
    return val.strip().lower().replace('(', '').replace(')', '')

def analyze_file(file_path):
    results = []
    with open(file_path, encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    double_vars = set()
    real_vars = set()
    real_assignments = defaultdict(set)  # var -> {'0', '1', 'other'}

    for lineno, line in enumerate(lines, 1):
        line_stripped = line.strip()

        # 检测 double precision 定义
        decl_match = double_precision_decl.search(line)
        if decl_match:
            vars_decl = decl_match.group(1)
            var_names = [v.strip().split('(')[0] for v in vars_decl.split(',')]
            for v in var_names:
                double_vars.add(v.lower())
                results.append({
                    'file': file_path,
                    'line': lineno,
                    'code': line_stripped,
                    'type': 'double precision 变量定义',
                    'suggestion': '检查是否真的需要双精度；否则建议改为 real'
                })

        # 检测双精度常量
        if double_constant.search(line):
            results.append({
                'file': file_path,
                'line': lineno,
                'code': line_stripped,
                'type': '双精度常量',
                'suggestion': '替换为单精度常量（如 1.0）或添加显式类型转换'
            })

        # 检测 float_t 使用
        if float_t_pattern.search(line):
            results.append({
                'file': file_path,
                'line': lineno,
                'code': line_stripped,
                'type': 'float_t 使用',
                'suggestion': 'float_t 可能默认为 double；如非必要请改用 real'
            })

        # 图形相关变量使用高精度
        if 'real' in line.lower() and re.search(r'(color|plot|graph|pixel|viz)', line, re.IGNORECASE):
            results.append({
                'file': file_path,
                'line': lineno,
                'code': line_stripped,
                'type': '图形变量使用高精度',
                'suggestion': '图形渲染相关数据通常无需高精度，建议使用 real 或 integer 类型'
            })

        # 检测混合精度配置项
        if 'SINGLE_PRECISION_POISSON' in line.upper():
            results.append({
                'file': file_path,
                'line': lineno,
                'code': line_stripped,
                'type': '混合精度配置项',
                'suggestion': '开启混合精度配置可能导致部分变量仍为双精度，请检查是否必要'
            })

        # 识别 real 类型变量
        real_decl = real_variable_pattern.search(line)
        if real_decl:
            var_part = real_decl.group(1)
            var_names = [v.strip().split('(')[0] for v in var_part.split(',')]
            for v in var_names:
                real_vars.add(v.lower())

        # 捕捉赋值
        assign_match = assignment_pattern.search(line)
        if assign_match:
            lhs, rhs = assign_match.groups()
            lhs = lhs.strip().lower()
            rhs_clean = normalize_value(rhs)

            if lhs in double_vars and is_simple_assignment(rhs_clean):
                results.append({
                    'file': file_path,
                    'line': lineno,
                    'code': line_stripped,
                    'type': '双精度变量仅用于简单赋值',
                    'suggestion': f'变量 "{lhs}" 仅用于简单赋值，考虑使用 real 类型'
                })

            if lhs in real_vars:
                if rhs_clean in boolean_like_values:
                    real_assignments[lhs].add(rhs_clean)
                else:
                    real_assignments[lhs].add('other')

    # real 类型仅赋值 0/1/zero/one，建议改为 logical
    for var, assigned_values in real_assignments.items():
        if assigned_values.issubset(boolean_like_values):
            for lineno, line in enumerate(lines, 1):
                if re.search(rf'\b{var}\b', line, re.IGNORECASE) and 'real' in line.lower():
                    results.append({
                        'file': file_path,
                        'line': lineno,
                        'code': line.strip(),
                        'type': 'real 类型变量用于布尔值',
                        'suggestion': f'变量 "{var}" 仅被赋值为 0/1 或 zero/one，建议改为 logical 类型以节省内存'
                    })
                    break

    return results

def analyze_directory(root_dir):
    all_results = []
    for root, _, files in os.walk(root_dir):
        for file in files:
            if any(file.lower().endswith(ext) for ext in FORTRAN_EXTENSIONS):
                full_path = os.path.join(root, file)
                all_results.extend(analyze_file(full_path))
    return all_results

def write_csv(results, output_path):
    with open(output_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['file', 'line', 'code', 'type', 'suggestion'])
        writer.writeheader()
        writer.writerows(results)

if __name__ == '__main__':
    project_dir = r'C:\Users\dell\Desktop\检测的CAE项目\8dealii-11-27'
    output_file = os.path.join(project_dir, 'unnecessary_double_report.csv')
    results = analyze_directory(project_dir)
    write_csv(results, output_file)
    print(f'✅ 检测完成，报告已保存至：{output_file}')
