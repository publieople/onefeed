# -*- coding: utf-8 -*-
"""量一次：选中前后，文字自身的位置、颜色、祖先容器有没有变。"""
import json
import os

TMP = os.path.join(r"E:\Documents\deepseek-harness\default-workspace\onefeed", ".onefeed", "tmp")
os.makedirs(TMP, exist_ok=True)
for n in ("TMP", "TEMP", "TMPDIR"):
    os.environ[n] = TMP

from playwright.sync_api import sync_playwright

JS = """(id) => {
  const b = document.querySelector('[data-value="' + id + '"]');
  const span = b.querySelector('span');
  const text = [...span.childNodes].find(n => n.nodeType === 3);
  const range = document.createRange();
  range.selectNodeContents(span);
  const r = range.getBoundingClientRect();
  return {
    chipX: +b.getBoundingClientRect().x.toFixed(1),
    spanX: +r.x.toFixed(1), spanW: +r.width.toFixed(1),
    color: getComputedStyle(span).color,
    parentTag: b.parentElement.tagName,
    parentClass: b.parentElement.className,
    transform: getComputedStyle(b.parentElement).transform,
    scaleX: +b.parentElement.getBoundingClientRect().width.toFixed(1),
  };
}"""

with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    pg = br.new_page(viewport={"width": 1440, "height": 900})
    pg.goto("http://127.0.0.1:8791/", wait_until="networkidle")
    pg.wait_for_selector('[data-value="juejin"]')
    pg.wait_for_timeout(500)
    print("掘金 选中前:", json.dumps(pg.evaluate(JS, "juejin"), ensure_ascii=False))
    print("抖音 选中前:", json.dumps(pg.evaluate(JS, "douyin"), ensure_ascii=False))

    pg.click('[data-value="juejin"]')
    pg.wait_for_timeout(45)
    print("掘金 选中后45ms:", json.dumps(pg.evaluate(JS, "juejin"), ensure_ascii=False))
    pg.wait_for_timeout(600)
    print("掘金 选中后稳住:", json.dumps(pg.evaluate(JS, "juejin"), ensure_ascii=False))

    pg.click('[data-value="douyin"]', modifiers=["Control"])
    pg.wait_for_timeout(45)
    print("抖音 Ctrl 加入45ms:", json.dumps(pg.evaluate(JS, "douyin"), ensure_ascii=False))
    pg.wait_for_timeout(600)
    print("抖音 Ctrl 加入稳住:", json.dumps(pg.evaluate(JS, "douyin"), ensure_ascii=False))
    print("掘金 旁边加入后:", json.dumps(pg.evaluate(JS, "juejin"), ensure_ascii=False))
    print("知乎(无关):", json.dumps(pg.evaluate(JS, "zhihu"), ensure_ascii=False))
    br.close()
