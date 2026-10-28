import os
import torch
import joblib
import pandas as pd
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from datetime import datetime
import re

# ====================== 模型配置 ============================
PRETRAINED_MODEL = "Salesforce/codet5-base"
MAX_LEN = 512
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

tokenizer = AutoTokenizer.from_pretrained(PRETRAINED_MODEL)
encoder = AutoModelForSeq2SeqLM.from_pretrained(PRETRAINED_MODEL).get_encoder().to(DEVICE)

clf = joblib.load("voting_code_smell_classifier.pkl")
label_encoder = joblib.load("voting_label_encoder.pkl")


# ====================== 嵌入向量 =============================
def get_code_embedding(code_snippet):
    inputs = tokenizer(
        code_snippet,
        return_tensors="pt",
        truncation=True,
        padding="max_length",
        max_length=MAX_LEN
    )
    inputs = {k: v.to(DEVICE) for k, v in inputs.items()}

    with torch.no_grad():
        encoder_outputs = encoder(**inputs)
        emb = encoder_outputs.last_hidden_state.mean(dim=1).squeeze(0).cpu().numpy()

    return emb


# ====================== 并行规则 + 风险评分 ==================
def detect_parallel_semantics_with_score(code: str):
    lowered = code.lower()
    score = 0
    reasons = []

    has_loop = bool(re.search(r"\b(for|while)\b", lowered))
    has_parallel = bool(re.search(r"\b(omp|tbb|mpi|parallel)\b", lowered))

    if has_loop:
        score += 10
        reasons.append("contains loop")

    # ---- Rule 1: 串行递推 → 过度并行 ----
    serial_patterns = [
        r"\w+\s*\+=\s*\w+",
        r"\w+\s*=\s*\w+\s*\+",
        r"\w+\s*=\s*\w+\s*\*"
    ]
    has_serial_dependency = any(re.search(p, lowered) for p in serial_patterns)

    if has_loop and has_serial_dependency:
        return "过度并行", 100 + score, "serial dependency inside loop"

    # ---- Rule 2: 矩阵初始化 + 循环 + 无并行 → 并行忽视 ----
    matrix_keywords = [
        "matrix", "vector", "sparse", "fullmatrix",
        "reinit", "resize", "initialize", "constructor"
    ]
    has_matrix_init = any(k in lowered for k in matrix_keywords)

    if has_loop and has_matrix_init and not has_parallel:
        return "并行忽视", 90 + score, "matrix initialization without parallelism"

    # ---- Rule 3: 可并行循环但未并行 ----
    if has_loop and not has_serial_dependency and not has_parallel:
        return "并行忽视", 80 + score, "potentially parallel loop without parallelism"

    return None, score, None


# ====================== 单段预测 =============================
def predict_code(code):
    # ① 规则判断
    rule_label, rule_score, reason = detect_parallel_semantics_with_score(code)
    if rule_label:
        return rule_label, rule_score, reason

    # ② 模型预测
    embedding = get_code_embedding(code)
    pred_id = clf.predict([embedding])[0]
    label = label_encoder.inverse_transform([pred_id])[0]

    score = 0
    if label == "过度并行":
        score = 60
    elif label == "并行忽视":
        score = 50

    return label, score, "model prediction"


# ====================== 文件遍历 =============================
def get_all_source_files(root):
    exts = (".c", ".cc", ".cpp", ".h")
    files = []

    for path, _, fs in os.walk(root):
        for f in fs:
            if f.endswith(exts):
                files.append(os.path.join(path, f))
    return files


# ====================== 切分代码 =============================
def split_file_into_snippets(filepath, window_size=40):
    with open(filepath, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    snippets = []
    for i in range(0, len(lines), window_size):
        code = "".join(lines[i:i + window_size])
        snippets.append((i + 1, i + window_size, code))

    return snippets


# ====================== 项目分析 =============================
def analyze_project(root_dir):
    files = get_all_source_files(root_dir)
    print(f"📁 共发现 {len(files)} 个 C/C++ 文件")

    results = []

    for file in files:
        print(f"🔍 分析：{file}")
        snippets = split_file_into_snippets(file)

        for start, end, code in snippets:
            if not code.strip():
                continue

            label, score, reason = predict_code(code)

            results.append({
                "file": file,
                "start_line": start,
                "end_line": end,
                "pred_label": label,
                "risk_score": score,
                "trigger_reason": reason,
                "code": code
            })

    return results


# ====================== 输出 CSV =============================
def save_csv(results, out_dir):
    df = pd.DataFrame(results)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    full_path = os.path.join(out_dir, f"dealii_代码异味预测_完整_{ts}.csv")
    df.to_csv(full_path, index=False, encoding="utf-8-sig")

    print(f"\n✅ 全量结果已输出：{full_path}")

    # ---- Top 100 高风险异味 ----
    top_df = df[
        df["pred_label"].isin(["过度并行", "并行忽视"])
    ].sort_values(by="risk_score", ascending=False).head(100)

    top_path = os.path.join(out_dir, f"dealii_Top100_并行异味_{ts}.csv")
    top_df.to_csv(top_path, index=False, encoding="utf-8-sig")

    print(f"🔥 Top 100 高风险并行异味已输出：{top_path}")


# ====================== 主入口 =============================
if __name__ == "__main__":
    ROOT_DIR = r"C:\Users\dell\Desktop\检测的CAE项目\9+26"

    results = analyze_project(ROOT_DIR)
    save_csv(results, ROOT_DIR)
