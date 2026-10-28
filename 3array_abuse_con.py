import os
import re
import csv
import pandas as pd
import difflib

# =================配置区域=================
# 项目源码根目录（确保下面真的有 .cpp/.h）
PROJECT_ROOT = r"C:\Users\dell\Desktop\检测的CAE项目\dealii-1-6"

# 历史异味知识库
KNOWLEDGE_BASE_PATH = r"C:\Users\dell\Desktop\检测的CAE项目\dealii-数组滥用.xlsx"

# 输出 CSV
OUTPUT_CSV = os.path.join(PROJECT_ROOT, "array_abuse_analysis_ranked.csv")

# 可信度阈值
CONFIDENCE_THRESHOLD = 40

# 相似度比对最大长度（防止大项目卡死）
MAX_COMPARE_LEN = 200

# Top-K（每个项目最多输出多少条）
TOP_K = 20
# =========================================


def is_code_file(filename):
    return filename.lower().endswith(('.cpp', '.cc', '.c', '.h', '.hpp'))


def load_known_smells(excel_path):
    if not os.path.exists(excel_path):
        print(f"[Warn] 未找到知识库：{excel_path}")
        return []

    try:
        df = pd.read_excel(excel_path)
        for col in df.columns:
            if '代码' in str(col) or 'code' in str(col).lower():
                return df[col].dropna().astype(str).tolist()

        return df.iloc[:, -1].dropna().astype(str).tolist()

    except Exception as e:
        print(f"[Error] Excel读取失败：{e}")
        return []


def calculate_similarity(code_snippet, known_smells):
    if not known_smells or not code_snippet:
        return 0.0

    code = re.sub(r'\s+', ' ', code_snippet).strip()[:MAX_COMPARE_LEN]
    max_ratio = 0.0

    for ks in known_smells:
        ks_clean = re.sub(r'\s+', ' ', ks).strip()[:MAX_COMPARE_LEN]
        ratio = difflib.SequenceMatcher(None, code, ks_clean).ratio()
        if ratio > max_ratio:
            max_ratio = ratio

    return max_ratio


def extract_matches_with_lines(code, patterns):
    results = []
    seen = set()
    lines = code.splitlines()

    for idx, p in enumerate(patterns):
        try:
            regex = re.compile(p)
        except re.error:
            continue

        for i, line in enumerate(lines, start=1):
            if regex.search(line):
                key = (i, line.strip())
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "line": i,
                        "content": line.strip(),
                        "pattern_index": idx
                    })
    return results


def detect_array_usage(code):
    static_patterns = [
        r'\b(?:int|float|double|char|bool|unsigned|long|short)\s+\w+\s*\[[^\]]+\]',
        r'\bstd::array<[^>]+>\s+\w+',
        r'GeometryInfo<[^>]+>::vertices_per_cell',
        r'std::fill\s*\(\s*std::begin'
    ]

    dynamic_patterns = [
        r'\bstd::vector<[^>]+>\s+\w+',
        r'\bboost::container::small_vector<[^>]+>\s+\w+',
        r'new\s+\w+\s*\['
    ]

    return (
        extract_matches_with_lines(code, static_patterns),
        extract_matches_with_lines(code, dynamic_patterns)
    )


def analyze_directory_ranked(root_path, output_csv_path, knowledge_path):
    if not os.path.exists(root_path):
        print(f"[Error] 项目路径不存在：{root_path}")
        return

    files = []
    for root, _, fs in os.walk(root_path):
        for f in fs:
            if is_code_file(f):
                files.append(os.path.join(root, f))

    print(f"[Info] 扫描文件数：{len(files)}")
    if not files:
        print("[Warn] 未发现任何 C/C++ 文件，请确认 PROJECT_ROOT 指向源码目录")
        return

    known_smells = load_known_smells(knowledge_path)
    results = []

    for path in files:
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                code = f.read()
        except Exception:
            continue

        static_hits, dynamic_hits = detect_array_usage(code)
        sc, dc = len(static_hits), len(dynamic_hits)
        total = sc + dc
        ratio = sc / total if total else 0

        # ---------- 可信度评分 ----------
        score = 0

        # 1) 混合使用最可疑
        if 0 < ratio < 1:
            score += 40
        elif ratio == 1 and sc > 0:
            score += 20

        # 2) 静态数组数量
        score += min(sc * 2, 20)

        # 3) 历史异味相似度
        best_sim, best_line, best_snip = 0, -1, ""
        for h in static_hits:
            sim = calculate_similarity(h["content"], known_smells)
            if sim > best_sim:
                best_sim = sim
                best_line = h["line"]
                best_snip = h["content"]

        if best_sim > 0.6:
            score += best_sim * 50

        score = round(score, 1)

        if score >= CONFIDENCE_THRESHOLD or (0 < ratio < 1):
            results.append({
                "file_path": path,
                "confidence": score,
                "core_loc": f"Line {best_line}" if best_line != -1 else "N/A",
                "static_count": sc,
                "dynamic_count": dc,
                "ratio": f"{ratio * 100:.1f}%",
                "snippet": best_snip[:120],
                "similarity_found": f"{best_sim * 100:.1f}%"
            })

    # ================= Top-20 压缩 =================
    results.sort(key=lambda x: x["confidence"], reverse=True)
    if len(results) > TOP_K:
        results = results[:TOP_K]
    # ==============================================

    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_csv_path), exist_ok=True)

    with open(output_csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        if results:
            writer = csv.DictWriter(
                f,
                fieldnames=list(results[0].keys()),
                extrasaction='ignore'
            )
            writer.writeheader()
            writer.writerows(results)

    print(f"[Done] 输出 Top-{len(results)} 个最可能被开发者确认的数组滥用实例")
    print(f"[Save] {output_csv_path}")


if __name__ == "__main__":
    analyze_directory_ranked(PROJECT_ROOT, OUTPUT_CSV, KNOWLEDGE_BASE_PATH)
