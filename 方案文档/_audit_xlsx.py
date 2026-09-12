# -*- coding: utf-8 -*-
import openpyxl
wb = openpyxl.load_workbook(r"D:\黑客松\赛题 1：数据共情者-业务数据.xlsx", data_only=True)
chat = list(wb["聊天记录"].iter_rows(values_only=True))
hdr, data = chat[0], chat[1:]
ix = {h: i for i, h in enumerate(hdr)}
for s in ["S00045","S00232","S00277","S00073"]:
    rows = [r for r in data if r[ix["会话ID"]]==s]
    if rows:
        print(s, rows[0][ix["买家昵称"]], rows[0][ix["scene_major"]], rows[0][ix["scene_minor"]], rows[0][ix["发送时间"]])
        print("  msg1:", str(rows[0][ix["message_text"]])[:50])
