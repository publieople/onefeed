import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from docx import Document
p = r"E:\Documents\deepseek-harness\default-workspace\onefeed\docs\submission\报名表-OneFeed-待补全.docx"
d = Document(p)

def set_cell(cell, text):
    paras = cell.paragraphs
    para = paras[0]
    if para.runs:
        para.runs[0].text = text
        for r in para.runs[1:]:
            r.text = ""
    else:
        para.add_run(text)
    for extra in paras[1:]:
        for r in extra.runs:
            r.text = ""

t0 = d.tables[0]
vals0 = ["【待填：队名】", "冯周杰", "人工智能学院", "人工智能", "2024 级（大三）", "14759026314", "【待填：微信号】"]
for i, v in enumerate(vals0):
    set_cell(t0.rows[i].cells[1], v)

t1 = d.tables[1]
rows = [
    ["1", "冯周杰（队长）", "人工智能学院", "人工智能", "2024 级", "开发 / 产品 / 路演"],
    ["2", "【待填：队员 2】", "【待填】", "【待填】", "【待填】", "【待填：开发 / 设计】"],
    ["3", "【待填：队员 3】", "【待填】", "【待填】", "【待填】", "【待填：开发 / 调研】"],
    ["4", "", "", "", "", ""],
    ["5", "", "", "", "", ""],
]
for ri, row in enumerate(rows, start=1):
    for ci, v in enumerate(row):
        set_cell(t1.rows[ri].cells[ci], v)

t2 = d.tables[2]
set_cell(t2.rows[0].cells[1], "AI+ 信息聚合（多平台内容聚合与智能筛选）")
set_cell(t2.rows[1].cells[1], "□ 是（请优先安排助教结对）　　☑ 否")
set_cell(t2.rows[2].cells[1], "□ 需要（希望匹配的角色：□开发 □设计 □调研 □路演 □不限）　　☑ 不需要")
set_cell(t2.rows[3].cells[1], "登录自己的账号，一屏刷完六个平台；插件即装即用，AI 合并同一件事、按一句话筛选。")

d.save(p)
print("saved", p)
d2 = Document(p)
for ti, tb in enumerate(d2.tables):
    print("--- table", ti)
    for r in tb.rows:
        print(" || ".join(c.text.strip() for c in r.cells))
