import os
import torch
import joblib
import pandas as pd
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from datetime import datetime

# ====================== 模型配置 ============================
PRETRAINED_MODEL = "Salesforce/codet5-base"
MAX_LEN = 512
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# 加载模型（投票分类器）
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


# ====================== 单段预测 =============================
def predict_code(code):
    embedding = get_code_embedding(code)
    pred_id = clf.predict([embedding])[0]
    label = label_encoder.inverse_transform([pred_id])[0]

    # 规则修正：若含 for/while 且预测为正常 → 修正为“并行忽视”
    lowered = code.lower()
    if label == "正常-不使用并行":
        if ("for " in lowered or "for(" in lowered or
                "while " in lowered or "while(" in lowered):
            return "并行忽视"

    return label


# ====================== 读取整个项目 ============================
def get_all_source_files(root):
    exts = (".c", ".cc", ".cpp", ".h")
    file_list = []

    for path, _, files in os.walk(root):
        for f in files:
            if f.endswith(exts):
                file_list.append(os.path.join(path, f))

    return file_list


# ====================== 将文件切分为片段 =========================
def split_file_into_snippets(filepath, window_size=40):
    """
    例如 window_size=40 行：每 40 行作为一个 snippet
    """
    with open(filepath, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    snippets = []
    total = len(lines)

    for i in range(0, total, window_size):
        code = "".join(lines[i:i + window_size])
        snippets.append((i + 1, i + window_size, code))

    return snippets


# ====================== 项目批量预测 ============================
def analyze_project(root_dir):
    files = get_all_source_files(root_dir)
    print(f"📁 共发现 {len(files)} 个 C/C++ 源码文件")

    results = []

    for file in files:
        print(f"🔍 正在分析：{file}")

        snippets = split_file_into_snippets(file, window_size=40)

        for (start_line, end_line, code) in snippets:
            if code.strip() == "":
                continue

            label = predict_code(code)

            results.append({
                "file": file,
                "start_line": start_line,
                "end_line": end_line,
                "pred_label": label,
                "code": code
            })

    return results


# ====================== 写 CSV ============================
def save_csv(results, out_dir):
    df = pd.DataFrame(results)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(out_dir, f"dealii_代码异味预测_{ts}.csv")

    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n✅ 预测完成，结果 CSV 已输出：{output_path}")


# ====================== 主入口 =============================
if __name__ == "__main__":
    ROOT_DIR = r"C:\Users\dell\Desktop\检测的CAE项目\8dealii-11-27"

    all_results = analyze_project(ROOT_DIR)
    save_csv(all_results, ROOT_DIR)
