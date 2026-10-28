import os
import re
import csv
from collections import defaultdict

CPP_EXTENSIONS = {'.c', '.cc', '.cpp', '.h', '.hpp'}

# 正则表达式定义
double_decl_pattern = re.compile(r'\bdouble\s+([\w,\s\[\]]+)', re.IGNORECASE)
float_literal_pattern = re.compile(r'\b\d+\.\d+\b')  # 1.0 / 0.5 等
simple_assign_pattern = re.compile(r'(\w+)\s*=\s*([^;]+);')
bool_like_values = {'0', '1', '0.0', '1.0'}

graphics_keywords = re.compile(
    r'(pixel|color|rgb|rgba|render|draw|visual|mesh|plot|image|screen|gui|gl_|vtk_)',
    re.IGNORECASE
)

float_suffix_pattern = re.compile(r'\b\d+\.\d+f\b')


def normalize(val):
    return val.strip().lower()


def analyze_file(file_path):
    results = []
    double_vars = set()
    double_assignments = defaultdict(list)

    with open(file_path, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()

        # --- 检测 double 声明 ---
        decl = double_decl_pattern.search(line)
        if decl:
            vars_part = decl.group(1)
            varlist = [v.strip().split('[')[0] for v in vars_part.split(',')]

            for v in varlist:
                varname = v.strip()
                if not varname:
                    continue
                double_vars.add(varname)

                results.append({
                    'file': file_path,
                    'line': lineno,
                    'code': stripped,
                    'type': 'double 变量定义',
                    'suggestion': '检查是否需要双精度，若无必要改为 float'
                })

        # --- 检测 double 变量用于简单赋值 ---
        assign = simple_assign_pattern.search(line)
        if assign:
            lhs, rhs = assign.groups()
            lhs_norm = lhs.strip()

            if lhs_norm in double_vars:
                rhs_norm = normalize(rhs)

                # 判断是否是简单常量赋值
                if rhs_norm in bool_like_values or re.fullmatch(r'\d+(\.\d+)?', rhs_norm):
                    results.append({
                        'file': file_path,
                        'line': lineno,
                        'code': stripped,
                        'type': 'double 仅用于简单常量赋值',
                        'suggestion': f'变量 "{lhs_norm}" 似乎不需要高精度，建议改为 float 或 bool'
                    })

        # --- 检测图形/可视化变量使用 double ---
        if 'double' in line.lower() and graphics_keywords.search(line):
            results.append({
                'file': file_path,
                'line': lineno,
                'code': stripped,
                'type': '图形/可视化变量误用 double',
                'suggestion': '图像/像素/颜色相关变量通常不需要 double，应使用 float 或 int'
            })

        # --- 检测 double 常量（未带 f） ---
        if float_literal_pattern.search(line) and not float_suffix_pattern.search(line):
            if 'float' in line:
                # float 却用 double 常量
                results.append({
                    'file': file_path,
                    'line': lineno,
                    'code': stripped,
                    'type': 'float 变量初始化使用了 double 常量',
                    'suggestion': '请使用 1.0f 形式避免隐式提升为 double'
                })

    return results


def analyze_directory(root_dir):
    all_results = []
    for root, _, files in os.walk(root_dir):
        for file in files:
            if any(file.lower().endswith(ext) for ext in CPP_EXTENSIONS):
                fullpath = os.path.join(root, file)
                all_results.extend(analyze_file(fullpath))
    return all_results


def write_csv(results, output_path):
    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['file', 'line', 'code', 'type', 'suggestion']
        )
        writer.writeheader()
        writer.writerows(results)


if __name__ == '__main__':
    project_dir = r'C:\Users\dell\Desktop\检测的CAE项目\8dealii-11-27'
    output_file = os.path.join(project_dir, 'unnecessary_double_cpp_report.csv')

    results = analyze_directory(project_dir)
    write_csv(results, output_file)

    print(f'✅ C/C++ 不必要双精度检测完成：{output_file}')
