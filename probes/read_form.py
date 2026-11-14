import sys
from docx import Document
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
d = Document(r"E:\Documents\xwechat_files\wxid_hyn0gfec57hc22_aa5e\temp\RWTemp\2026-11\57d03f77d97ecb64217d99d800bbf9fa\附件1_报名表.docx")
print("PARAGRAPHS")
for i, para in enumerate(d.paragraphs):
    t = para.text.strip()
    if t:
        print(i, "|", t)
print("TABLES", len(d.tables))
for ti, tb in enumerate(d.tables):
    print("--- table", ti, "rows", len(tb.rows), "cols", len(tb.columns))
    for r in tb.rows:
        print(" || ".join(c.text.replace("\n", " / ").strip() for c in r.cells))
