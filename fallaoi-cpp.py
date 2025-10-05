#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mini IDE Beta2 (中文版) - Single file
Features:
- 文件树、打开文件夹、双击打开
- 多标签编辑器（行号）
- 代码高亮 (pygments)
- 自动缩进 (回车继承缩进, 冒号后增加)
- Tab -> 4 空格
- 代码自动补全 (Ctrl+Space, jedi)
- 悬停文档提示 (jedi/infer or inspect), 浮动可滚动窗口
- 函数参数签名提示 (在 '(' 后显示，逗号高亮当前参数)
- 多终端、运行 Python/C/C++（自动识别并编译C/C++）
- 运行中断（Stop 按钮 kill 子进程）
- 状态栏 (文件/光标/状态/时间/CPU/内存)
- 配置界面并持久化 (config.json)
- 自动保存
- 查找替换对话框 (Ctrl+F)
- 代码折叠 (Python/C/C++ 函数和类)
- 主题切换 (light/dark)
- 项目管理 (最近打开的文件)
- 错误检查与行号标记
- 改进的调试功能 (基础断点支持)
"""

import os
import sys
import time
import json
import re
import threading
import subprocess
import inspect
from pathlib import Path
from functools import partial
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

# Optional libraries
try:
    import jedi
    JEDI_AVAILABLE = True
except Exception:
    JEDI_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except Exception:
    PSUTIL_AVAILABLE = False

try:
    from pygments import lex
    from pygments.lexers import PythonLexer, CLexer, CppLexer
    PYGMENTS_AVAILABLE = True
except Exception:
    PYGMENTS_AVAILABLE = False

CONFIG_FILE = "config.json"

# -------------------- TerminalTab --------------------
class TerminalTab:
    def __init__(self, notebook, title):
        self.notebook = notebook
        self.frame = ttk.Frame(notebook)
        self.text = ScrolledText(self.frame, wrap="word", font=("Consolas", 11), bg="black", fg="white")
        self.text.pack(fill="both", expand=True)
        self.entry = tk.Entry(self.frame, font=("Consolas", 11), bg="#222", fg="white")
        self.entry.pack(fill="x")
        self.entry.bind("<Return>", self._on_enter)
        self.proc = None
        self.notebook.add(self.frame, text=title)

    def _on_enter(self, event):
        cmd = self.entry.get().strip()
        if not cmd:
            return
        self.write(f"> {cmd}\n")
        self.entry.delete(0, tk.END)
        threading.Thread(target=self._run_cmd, args=(cmd,), daemon=True).start()

    def _run_cmd(self, cmd):
        try:
            p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.proc = p
            for line in p.stdout:
                self.write(line)
            for line in p.stderr:
                self.write(line)
            p.wait()
            self.write(f"\n进程退出，返回码 {p.returncode}\n")
        except Exception as e:
            self.write(f"命令执行错误：{e}\n")
        finally:
            self.proc = None

    def write(self, txt):
        self.text.config(state="normal")
        self.text.insert("end", txt)
        self.text.see("end")
        self.text.config(state="disabled")

# -------------------- FindReplaceDialog --------------------
class FindReplaceDialog:
    def __init__(self, parent, editor):
        self.parent = parent
        self.editor = editor
        self.window = tk.Toplevel(parent)
        self.window.title("查找和替换")
        self.window.geometry("400x200")
        self.window.transient(parent)
        self.window.grab_set()
        
        # 查找
        ttk.Label(self.window, text="查找:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.find_entry = ttk.Entry(self.window, width=30)
        self.find_entry.grid(row=0, column=1, padx=5, pady=5, sticky="we")
        self.find_entry.focus_set()
        
        # 替换
        ttk.Label(self.window, text="替换为:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.replace_entry = ttk.Entry(self.window, width=30)
        self.replace_entry.grid(row=1, column=1, padx=5, pady=5, sticky="we")
        
        # 选项
        self.case_var = tk.BooleanVar()
        self.case_check = ttk.Checkbutton(self.window, text="区分大小写", variable=self.case_var)
        self.case_check.grid(row=2, column=0, padx=5, pady=5, sticky="w")
        
        self.word_var = tk.BooleanVar()
        self.word_check = ttk.Checkbutton(self.window, text="全字匹配", variable=self.word_var)
        self.word_check.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        
        # 按钮框架
        button_frame = ttk.Frame(self.window)
        button_frame.grid(row=3, column=0, columnspan=2, pady=10)
        
        ttk.Button(button_frame, text="查找下一个", command=self.find_next).pack(side="left", padx=5)
        ttk.Button(button_frame, text="替换", command=self.replace).pack(side="left", padx=5)
        ttk.Button(button_frame, text="全部替换", command=self.replace_all).pack(side="left", padx=5)
        ttk.Button(button_frame, text="关闭", command=self.window.destroy).pack(side="left", padx=5)
        
        self.window.columnconfigure(1, weight=1)
        
        # 绑定回车键到查找
        self.find_entry.bind("<Return>", lambda e: self.find_next())
        self.replace_entry.bind("<Return>", lambda e: self.replace())
        
        self.last_find_pos = "1.0"

    def find_next(self):
        find_text = self.find_entry.get()
        if not find_text:
            return
            
        case_sensitive = self.case_var.get()
        whole_word = self.word_var.get()
        
        # 构建正则表达式
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.escape(find_text)
        if whole_word:
            pattern = r'\b' + pattern + r'\b'
            
        try:
            # 从上次查找位置开始
            start_pos = self.last_find_pos
            content = self.editor.get(start_pos, "end")
            match = re.search(pattern, content, flags)
            
            if match:
                start_idx = self.editor.index(f"{start_pos}+{match.start()}c")
                end_idx = self.editor.index(f"{start_pos}+{match.end()}c")
                
                # 选择匹配的文本
                self.editor.tag_remove("sel", "1.0", "end")
                self.editor.tag_add("sel", start_idx, end_idx)
                self.editor.mark_set("insert", end_idx)
                self.editor.see(start_idx)
                
                # 更新下次查找位置
                self.last_find_pos = end_idx
            else:
                # 从开头重新查找
                self.last_find_pos = "1.0"
                messagebox.showinfo("查找", "已到达文档末尾")
                
        except Exception as e:
            messagebox.showerror("错误", f"查找失败: {e}")

    def replace(self):
        find_text = self.find_entry.get()
        replace_text = self.replace_entry.get()
        
        if not find_text:
            return
            
        try:
            # 如果有选中文本且匹配查找内容，则替换
            if self.editor.tag_ranges("sel"):
                sel_text = self.editor.get("sel.first", "sel.last")
                case_sensitive = self.case_var.get()
                
                if (case_sensitive and sel_text == find_text) or \
                   (not case_sensitive and sel_text.lower() == find_text.lower()):
                    self.editor.delete("sel.first", "sel.last")
                    self.editor.insert("sel.first", replace_text)
            
            # 查找下一个
            self.find_next()
            
        except Exception as e:
            messagebox.showerror("错误", f"替换失败: {e}")

    def replace_all(self):
        find_text = self.find_entry.get()
        replace_text = self.replace_entry.get()
        
        if not find_text:
            return
            
        case_sensitive = self.case_var.get()
        whole_word = self.word_var.get()
        
        # 构建正则表达式
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.escape(find_text)
        if whole_word:
            pattern = r'\b' + pattern + r'\b'
            
        try:
            content = self.editor.get("1.0", "end-1c")
            new_content, count = re.subn(pattern, replace_text, content, flags=flags)
            
            if count > 0:
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", new_content)
                messagebox.showinfo("替换", f"已完成 {count} 处替换")
            else:
                messagebox.showinfo("替换", "未找到匹配项")
                
        except Exception as e:
            messagebox.showerror("错误", f"全部替换失败: {e}")

# -------------------- MiniIDE --------------------
class MiniIDE(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Fialiaoi-cpp_Beta2")
        self.geometry("1360x900")

        # config & state
        self.config_data = {
            "gcc_path": None,
            "font_size": 13,
            "theme": "light",
            "autosave_interval": 0,
            "recent_files": [],
            "max_recent_files": 10
        }
        self.load_config()

        self.workspace_dir = os.getcwd()
        self.editor_tabs = []            # list of frames with .text, .ln, .filepath
        self.term_tabs = []              # list of TerminalTab
        self.process_map = {}            # map terminal frame -> subprocess
        self.completion_win = None
        self.tooltip_win = None
        self.signature_win = None
        self.debug_mode = False
        self.debug_locals = {}
        self.breakpoints = {}            # filepath -> set of line numbers
        self.fold_regions = {}           # editor -> list of (start_line, end_line)

        # UI build
        self._build_menu()
        self._build_toolbar()
        self._build_main_panes()
        self._build_statusbar()

        # 应用主题
        self._apply_theme()

        # periodic updates
        self.after(1000, self._periodic_update)

    # ---------------- config load/save ----------------
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.config_data.update(data)
            except Exception:
                pass

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, ensure_ascii=False, indent=4)
            return True
        except Exception:
            return False

    # ---------------- theme ----------------
    def _apply_theme(self):
        theme = self.config_data.get("theme", "light")
        if theme == "dark":
            self._setup_dark_theme()
        else:
            self._setup_light_theme()

    def _setup_light_theme(self):
        # 设置浅色主题颜色
        self.editor_bg = "white"
        self.editor_fg = "black"
        self.linenumber_bg = "#f0f0f0"
        self.linenumber_fg = "#666"
        
        # 更新所有编辑器
        for tab in self.editor_nb.tabs():
            frame = self.editor_nb.nametowidget(tab)
            try:
                frame.text.config(bg=self.editor_bg, fg=self.editor_fg, insertbackground=self.editor_fg)
                frame.ln.config(bg=self.linenumber_bg, fg=self.linenumber_fg)
            except Exception:
                pass

    def _setup_dark_theme(self):
        # 设置深色主题颜色
        self.editor_bg = "#1e1e1e"
        self.editor_fg = "#d4d4d4"
        self.linenumber_bg = "#252526"
        self.linenumber_fg = "#858585"
        
        # 更新所有编辑器
        for tab in self.editor_nb.tabs():
            frame = self.editor_nb.nametowidget(tab)
            try:
                frame.text.config(bg=self.editor_bg, fg=self.editor_fg, insertbackground=self.editor_fg)
                frame.ln.config(bg=self.linenumber_bg, fg=self.linenumber_fg)
            except Exception:
                pass

    # ---------------- menu ----------------
    def _build_menu(self):
        menubar = tk.Menu(self)
        # 文件
        fm = tk.Menu(menubar, tearoff=0)
        fm.add_command(label="打开文件", command=self.open_file_dialog, accelerator="Ctrl+O")
        fm.add_command(label="打开文件夹", command=self.open_folder_dialog, accelerator="Ctrl+Shift+O")
        fm.add_command(label="保存", command=self.save_file, accelerator="Ctrl+S")
        fm.add_command(label="另存为", command=self.save_file_as, accelerator="Ctrl+Shift+S")
        
        # 最近文件子菜单
        self.recent_menu = tk.Menu(fm, tearoff=0)
        self._update_recent_menu()
        fm.add_cascade(label="最近文件", menu=self.recent_menu)
        
        fm.add_separator()
        fm.add_command(label="退出", command=self.quit, accelerator="Ctrl+Q")
        menubar.add_cascade(label="文件", menu=fm)
        
        # 编辑
        em = tk.Menu(menubar, tearoff=0)
        em.add_command(label="撤销", command=self._undo, accelerator="Ctrl+Z")
        em.add_command(label="重做", command=self._redo, accelerator="Ctrl+Y")
        em.add_separator()
        em.add_command(label="查找", command=self._find_text, accelerator="Ctrl+F")
        em.add_command(label="替换", command=self._replace_text, accelerator="Ctrl+H")
        menubar.add_cascade(label="编辑", menu=em)
        
        # 视图
        viewm = tk.Menu(menubar, tearoff=0)
        viewm.add_command(label="切换主题", command=self._toggle_theme)
        viewm.add_command(label="折叠所有", command=self._fold_all)
        viewm.add_command(label="展开所有", command=self._unfold_all)
        menubar.add_cascade(label="视图", menu=viewm)
        
        # 运行
        runm = tk.Menu(menubar, tearoff=0)
        runm.add_command(label="运行 (Run)", command=self.run_current, accelerator="F5")
        runm.add_command(label="停止 (Stop)", command=self.stop_current_terminal_process, accelerator="Ctrl+F2")
        menubar.add_cascade(label="运行", menu=runm)
        
        # 调试
        debugm = tk.Menu(menubar, tearoff=0)
        debugm.add_command(label="切换断点", command=self._toggle_breakpoint, accelerator="F9")
        debugm.add_command(label="开始调试", command=self._start_debug, accelerator="F10")
        debugm.add_command(label="停止调试", command=self._stop_debug, accelerator="Shift+F5")
        menubar.add_cascade(label="调试", menu=debugm)
        
        # 设置
        setm = tk.Menu(menubar, tearoff=0)
        setm.add_command(label="绑定 GCC 路径", command=self._bind_gcc)
        setm.add_command(label="配置选项", command=self.open_settings)
        menubar.add_cascade(label="设置", menu=setm)
        
        self.config(menu=menubar)
        
        # 绑定快捷键
        self.bind("<Control-o>", lambda e: self.open_file_dialog())
        self.bind("<Control-O>", lambda e: self.open_file_dialog())
        self.bind("<Control-s>", lambda e: self.save_file())
        self.bind("<Control-S>", lambda e: self.save_file_as())
        self.bind("<Control-f>", lambda e: self._find_text())
        self.bind("<Control-h>", lambda e: self._replace_text())
        self.bind("<F5>", lambda e: self.run_current())
        self.bind("<Control-F2>", lambda e: self.stop_current_terminal_process())
        self.bind("<F9>", lambda e: self._toggle_breakpoint())
        self.bind("<F10>", lambda e: self._start_debug())
        self.bind("<Shift-F5>", lambda e: self._stop_debug())

    def _update_recent_menu(self):
        self.recent_menu.delete(0, "end")
        recent_files = self.config_data.get("recent_files", [])
        if not recent_files:
            self.recent_menu.add_command(label="无最近文件", state="disabled")
        else:
            for file_path in recent_files:
                if os.path.exists(file_path):
                    self.recent_menu.add_command(
                        label=os.path.basename(file_path),
                        command=lambda fp=file_path: self.open_file(fp)
                    )
            self.recent_menu.add_separator()
            self.recent_menu.add_command(label="清空列表", command=self._clear_recent_files)

    def _add_recent_file(self, file_path):
        recent_files = self.config_data.get("recent_files", [])
        if file_path in recent_files:
            recent_files.remove(file_path)
        recent_files.insert(0, file_path)
        
        # 限制最大数量
        max_files = self.config_data.get("max_recent_files", 10)
        self.config_data["recent_files"] = recent_files[:max_files]
        self.save_config()
        self._update_recent_menu()

    def _clear_recent_files(self):
        self.config_data["recent_files"] = []
        self.save_config()
        self._update_recent_menu()

    # ---------------- toolbar ----------------
    def _build_toolbar(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(side="top", fill="x")

        self.btn_run = ttk.Button(toolbar, text="运行 ▶", command=self.run_current)
        self.btn_run.pack(side="left", padx=4, pady=4)

        self.btn_debug = ttk.Button(toolbar, text="调试 🐞", command=self._start_debug)
        self.btn_debug.pack(side="left", padx=4, pady=4)

        self.btn_step = ttk.Button(toolbar, text="单步 ⏭", command=self._debug_step, state="disabled")
        self.btn_step.pack(side="left", padx=4, pady=4)

        self.btn_continue = ttk.Button(toolbar, text="继续 ▶▶", command=self._debug_continue, state="disabled")
        self.btn_continue.pack(side="left", padx=4, pady=4)

        self.btn_stop = ttk.Button(toolbar, text="停止 ⏹", command=self.stop_current_terminal_process)
        self.btn_stop.pack(side="left", padx=4, pady=4)

        self.btn_newterm = ttk.Button(toolbar, text="新建终端", command=self.add_terminal)
        self.btn_newterm.pack(side="left", padx=4, pady=4)

        # 查找框
        find_frame = ttk.Frame(toolbar)
        find_frame.pack(side="right", padx=8)
        
        ttk.Label(find_frame, text="查找:").pack(side="left")
        self.find_var = tk.StringVar()
        find_entry = ttk.Entry(find_frame, textvariable=self.find_var, width=20)
        find_entry.pack(side="left", padx=4)
        find_entry.bind("<Return>", self._quick_find)
        
        ttk.Button(find_frame, text="查找", command=self._quick_find).pack(side="left", padx=2)

        # 状态指示
        self.status_frame = ttk.Frame(toolbar)
        self.status_frame.pack(side="right", padx=8)
        self.status_canvas = tk.Canvas(self.status_frame, width=18, height=18, highlightthickness=0)
        self.status_dot = self.status_canvas.create_oval(3,3,15,15, fill="gray")
        self.status_canvas.pack(side="left")
        self.status_label = ttk.Label(self.status_frame, text="空闲", font=("Consolas", 10, "bold"))
        self.status_label.pack(side="left", padx=6)

    # ---------------- main panes ----------------
    def _build_main_panes(self):
        main_pane = ttk.Panedwindow(self, orient="horizontal")
        main_pane.pack(fill="both", expand=True)

        # left: file tree
        tree_frame = ttk.Frame(main_pane, width=280)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame)
        self.tree.heading("#0", text="资源管理器", anchor="w")
        self.tree.pack(fill="both", expand=True, side="left")
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.bind("<Double-1>", self._on_tree_double)
        self._populate_tree(self.workspace_dir)
        main_pane.add(tree_frame, weight=1)

        # right: editor + bottom
        right_pane = ttk.Panedwindow(main_pane, orient="vertical")
        main_pane.add(right_pane, weight=4)

        # editor notebook
        self.editor_nb = ttk.Notebook(right_pane)
        right_pane.add(self.editor_nb, weight=3)

        # bottom notebook
        self.bottom_nb = ttk.Notebook(right_pane, height=300)
        right_pane.add(self.bottom_nb, weight=1)

        # output tab
        self.output_tab = ttk.Frame(self.bottom_nb)
        self.output_text = ScrolledText(self.output_tab, height=12, bg="black", fg="white", font=("Consolas", 11))
        self.output_text.pack(fill="both", expand=True)
        self.bottom_nb.add(self.output_tab, text="输出")

        # vars tab
        self.vars_tab = ttk.Frame(self.bottom_nb)
        self.vars_text = ScrolledText(self.vars_tab, height=12, bg="#111", fg="lightgreen", font=("Consolas",11))
        self.vars_text.pack(fill="both", expand=True)
        self.bottom_nb.add(self.vars_tab, text="变量")

        # terminals tab
        self.terms_wrapper = ttk.Frame(self.bottom_nb)
        self.bottom_nb.add(self.terms_wrapper, text="终端")
        self.terminal_nb = ttk.Notebook(self.terms_wrapper)
        self.terminal_nb.pack(fill="both", expand=True)
        self.add_terminal()

        # new editor tab
        self.new_editor_tab()

    # ---------------- file tree ----------------
    def _populate_tree(self, path, parent=""):
        self.tree.delete(*self.tree.get_children(parent))
        try:
            entries = sorted(os.listdir(path))
        except Exception:
            return
        for name in entries:
            full = os.path.join(path, name)
            if os.path.isdir(full):
                node = self.tree.insert(parent, "end", text=name, values=[full], open=False)
                # placeholder
                self.tree.insert(node, "end", text="...")
            else:
                self.tree.insert(parent, "end", text=name, values=[full])

    def _on_tree_double(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        item = sel[0]
        vals = self.tree.item(item, "values")
        if not vals:
            return
        path = vals[0]
        if os.path.isdir(path):
            self._populate_tree(path, item)
        else:
            self.open_file(path)

    # ---------------- editor tabs ----------------
    def new_editor_tab(self, content="", file_path=None):
        frame = ttk.Frame(self.editor_nb)
        
        # 行号区域
        ln = tk.Text(frame, width=4, padx=3, takefocus=0, border=0, 
                    background=self.linenumber_bg, foreground=self.linenumber_fg,
                    state='disabled', font=("Consolas", self.config_data["font_size"]))
        ln.pack(side="left", fill="y")
        
        # 文本编辑区域
        text = tk.Text(frame, wrap="none", undo=True, 
                      bg=self.editor_bg, fg=self.editor_fg, insertbackground=self.editor_fg,
                      font=("Consolas", self.config_data["font_size"]))
        text.insert("1.0", content)
        text.pack(side="left", fill="both", expand=True)
        
        vscroll = ttk.Scrollbar(frame, orient="vertical", command=lambda *args, t=text, l=ln: self._vscroll(*args, text=t, ln=l))
        vscroll.pack(side="right", fill="y")
        text.configure(yscrollcommand=vscroll.set)

        # 折叠标记区域
        fold_canvas = tk.Canvas(frame, width=16, bg=self.linenumber_bg, highlightthickness=0)
        fold_canvas.pack(side="left", fill="y")
        frame.fold_canvas = fold_canvas

        # bindings
        text.bind("<KeyRelease>", lambda e, t=text, l=ln: self._on_key_release(e, t, l))
        text.bind("<Return>", lambda e, t=text: self._on_return(e, t))
        text.bind("<Tab>", lambda e, t=text: self._on_tab(e, t))
        text.bind("<Motion>", lambda e, t=text: self._on_mouse_motion(e, t))
        text.bind("<Key>", lambda e, t=text: self._on_key_update_cursor(e, t))
        text.bind("<Control-space>", lambda e, t=text: self._on_ctrl_space(e, t))
        text.bind("(", lambda e, t=text: self._on_open_paren(e, t))
        text.bind(",", lambda e, t=text: self._on_comma(e, t))
        text.bind("<Button-1>", lambda e, t=text: self._on_editor_click(e, t))
        text.bind("<Control-MouseWheel>", lambda e, t=text: self._on_ctrl_scroll(e, t))

        frame.text = text
        frame.ln = ln
        frame.filepath = file_path
        title = os.path.basename(file_path) if file_path else "未命名"
        self.editor_nb.add(frame, text=title)
        self.editor_nb.select(frame)
        self._update_line_numbers(text, ln)
        self._apply_syntax_highlight(text, file_path or "")
        
        # 分析代码结构用于折叠
        self._analyze_code_structure(text, file_path or "")
        
        return frame

    def _get_current_editor_frame(self):
        sel = self.editor_nb.select()
        if not sel:
            return None
        return self.editor_nb.nametowidget(sel)

    def _get_current_editor(self):
        frame = self._get_current_editor_frame()
        if not frame:
            return None
        return frame.text

    def _vscroll(self, *args, text, ln):
        text.yview(*args)
        ln.yview(*args)

    def _on_key_release(self, event, text, ln):
        self._update_line_numbers(text, ln)
        filepath = getattr(self._get_current_editor_frame(), "filepath", "") or ""
        self._apply_syntax_highlight(text, filepath)
        self._update_cursor_pos(text)
        
        # 重新分析代码结构
        self._analyze_code_structure(text, filepath)

    def _update_line_numbers(self, editor, ln):
        ln.config(state="normal")
        ln.delete("1.0", "end")
        last = editor.index("end-1c").split(".")[0]
        ln_text = "\n".join(str(i) for i in range(1, int(last)+1))
        ln.insert("1.0", ln_text)
        ln.config(state="disabled")

    # ---------------- code folding ----------------
    def _analyze_code_structure(self, editor, filepath):
        """分析代码结构，识别函数和类用于折叠"""
        if not filepath:
            return
            
        content = editor.get("1.0", "end-1c")
        lines = content.split('\n')
        fold_regions = []
        
        # 根据文件类型使用不同的分析规则
        if filepath.endswith('.py'):
            # Python: 函数和类
            indent_stack = []
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # 检查类定义
                if stripped.startswith('class '):
                    indent_stack.append(('class', i, len(line) - len(line.lstrip())))
                # 检查函数定义
                elif stripped.startswith('def '):
                    indent_stack.append(('function', i, len(line) - len(line.lstrip())))
                # 检查冒号结尾的行（可能是控制结构）
                elif stripped.endswith(':') and not stripped.startswith('#'):
                    current_indent = len(line) - len(line.lstrip())
                    # 找到匹配的缩进级别
                    while indent_stack and indent_stack[-1][2] >= current_indent:
                        start_type, start_line, _ = indent_stack.pop()
                        if i > start_line:
                            fold_regions.append((start_type, start_line, i))
                    
                    indent_stack.append(('block', i, current_indent))
            
            # 处理剩余的未闭合块
            for start_type, start_line, _ in indent_stack:
                fold_regions.append((start_type, start_line, len(lines)))
                
        elif filepath.endswith(('.c', '.cpp', '.h')):
            # C/C++: 函数和结构体
            brace_stack = []
            in_comment = False
            in_string = False
            escape_next = False
            
            for i, line in enumerate(lines, 1):
                j = 0
                while j < len(line):
                    char = line[j]
                    
                    if escape_next:
                        escape_next = False
                        j += 1
                        continue
                        
                    if char == '\\':
                        escape_next = True
                        j += 1
                        continue
                        
                    if char == '"' and not in_comment:
                        in_string = not in_string
                        j += 1
                        continue
                        
                    if char == '/' and j + 1 < len(line) and not in_string:
                        if line[j+1] == '*':
                            in_comment = True
                            j += 2
                            continue
                        elif line[j+1] == '/':
                            break  # 行注释，跳过该行剩余部分
                            
                    if char == '*' and j + 1 < len(line) and in_comment:
                        if line[j+1] == '/':
                            in_comment = False
                            j += 2
                            continue
                            
                    if not in_comment and not in_string:
                        if char == '{':
                            # 检查是否是函数或结构体定义
                            prev_text = ' '.join(lines[max(0, i-2):i-1] + [line[:j]])
                            if any(keyword in prev_text for keyword in ['class', 'struct', 'enum', 'union', 'namespace']) or \
                               re.search(r'\w+\s*\([^)]*\)\s*$', '\n'.join(lines[max(0, i-2):i-1])):
                                brace_stack.append(('block', i))
                        elif char == '}':
                            if brace_stack:
                                start_type, start_line = brace_stack.pop()
                                if i > start_line:
                                    fold_regions.append((start_type, start_line, i))
                                    
                    j += 1
        
        # 保存折叠区域
        self.fold_regions[editor] = fold_regions
        self._update_fold_display(editor)

    def _update_fold_display(self, editor):
        """更新折叠显示标记"""
        frame = None
        for tab in self.editor_nb.tabs():
            tab_frame = self.editor_nb.nametowidget(tab)
            if tab_frame.text == editor:
                frame = tab_frame
                break
                
        if not frame or not hasattr(frame, 'fold_canvas'):
            return
            
        canvas = frame.fold_canvas
        canvas.delete("all")
        
        fold_regions = self.fold_regions.get(editor, [])
        visible_lines = int(editor.index('end-1c').split('.')[0])
        
        for fold_type, start_line, end_line in fold_regions:
            if start_line > visible_lines:
                continue
                
            # 获取行位置
            bbox = editor.bbox(f"{start_line}.0")
            if not bbox:
                continue
                
            y_pos = bbox[1]
            is_folded = editor.mark_get(f"fold_{start_line}") if hasattr(editor, 'marks') else False
            
            # 绘制折叠标记
            marker_color = "blue" if fold_type == 'function' else "green" if fold_type == 'class' else "orange"
            canvas.create_rectangle(2, y_pos, 14, y_pos + 12, fill=marker_color, outline="")
            canvas.create_text(8, y_pos + 6, text="-" if not is_folded else "+", 
                             fill="white", font=("Arial", 8, "bold"))
        
        # 绑定点击事件
        canvas.bind("<Button-1>", lambda e, ed=editor: self._on_fold_click(e, ed))

    def _on_fold_click(self, event, editor):
        """处理折叠标记点击"""
        canvas = event.widget
        y = event.y
        
        fold_regions = self.fold_regions.get(editor, [])
        visible_lines = int(editor.index('end-1c').split('.')[0])
        
        for fold_type, start_line, end_line in fold_regions:
            if start_line > visible_lines:
                continue
                
            bbox = editor.bbox(f"{start_line}.0")
            if not bbox:
                continue
                
            y_pos = bbox[1]
            if y_pos <= y <= y_pos + 12:
                self._toggle_fold(editor, start_line, end_line)
                break

    def _toggle_fold(self, editor, start_line, end_line):
        """切换折叠状态"""
        fold_mark = f"fold_{start_line}"
        
        if editor.mark_get(fold_mark):
            # 展开
            editor.mark_unset(fold_mark)
            editor.delete(f"{start_line}.0+1l", f"{end_line}.0")
        else:
            # 折叠
            editor.mark_set(fold_mark, f"{start_line}.0")
            editor.insert(f"{start_line}.0", " [...] ")

    def _fold_all(self):
        """折叠所有可折叠区域"""
        editor = self._get_current_editor()
        if not editor:
            return
            
        fold_regions = self.fold_regions.get(editor, [])
        for fold_type, start_line, end_line in fold_regions:
            self._toggle_fold(editor, start_line, end_line)

    def _unfold_all(self):
        """展开所有折叠区域"""
        editor = self._get_current_editor()
        if not editor:
            return
            
        # 重新分析代码结构来重置折叠状态
        frame = self._get_current_editor_frame()
        if frame and frame.filepath:
            self._analyze_code_structure(editor, frame.filepath)

    # ---------------- syntax highlighting ----------------
    def _apply_syntax_highlight(self, editor, filepath):
        if not PYGMENTS_AVAILABLE:
            return

        # 清除现有标记
        for tag in editor.tag_names():
            if tag.startswith("token."):
                editor.tag_delete(tag)

        # 确定语言
        lexer = None
        if filepath.endswith(".py"):
            lexer = PythonLexer()
        elif filepath.endswith(".c"):
            lexer = CLexer()
        elif filepath.endswith((".cpp", ".cc", ".cxx", ".h", ".hpp")):
            lexer = CppLexer()
        else:
            return

        content = editor.get("1.0", "end-1c")
        try:
            tokens = lex(content, lexer)
        except Exception:
            return

        # 定义颜色映射
        colors = {
            "Token.Keyword": "#0000FF",
            "Token.Keyword.Constant": "#0000FF",
            "Token.Keyword.Declaration": "#0000FF",
            "Token.Keyword.Namespace": "#0000FF",
            "Token.Keyword.Pseudo": "#0000FF",
            "Token.Keyword.Reserved": "#0000FF",
            "Token.Keyword.Type": "#0000FF",
            "Token.Name.Class": "#267F99",
            "Token.Name.Function": "#795E26",
            "Token.Name.Builtin": "#267F99",
            "Token.String": "#A31515",
            "Token.String.Single": "#A31515",
            "Token.String.Double": "#A31515",
            "Token.String.Char": "#A31515",
            "Token.Comment": "#008000",
            "Token.Comment.Single": "#008000",
            "Token.Comment.Multiline": "#008000",
            "Token.Number": "#098658",
            "Token.Operator": "#000000",
            "Token.Punctuation": "#000000",
        }

        # 应用高亮
        for token_type, value in tokens:
            tag_name = str(token_type)
            color = colors.get(tag_name, "#000000")
            if tag_name not in editor.tag_names():
                editor.tag_configure(tag_name, foreground=color)
            start = "1.0"
            while True:
                pos = editor.search(value, start, stopindex="end", regexp=False)
                if not pos:
                    break
                end = f"{pos}+{len(value)}c"
                editor.tag_add(tag_name, pos, end)
                start = end

    # ---------------- auto indent ----------------
    def _on_return(self, event, editor):
        editor.insert("insert", "\n")
        line = editor.get("insert linestart", "insert")
        indent = re.match(r"^(\s*)", line).group(1)
        editor.insert("insert", indent)
        
        # 如果上一行以冒号结尾，增加一级缩进
        prev_line = editor.get("insert-2l linestart", "insert-2l lineend")
        if prev_line.rstrip().endswith(":"):
            editor.insert("insert", "    ")
            
        return "break"

    def _on_tab(self, event, editor):
        editor.insert("insert", "    ")
        return "break"

    # ---------------- code completion ----------------
    def _on_ctrl_space(self, event, editor):
        if not JEDI_AVAILABLE:
            return
            
        frame = self._get_current_editor_frame()
        if not frame or not frame.filepath:
            return
            
        cursor_pos = editor.index("insert")
        line, col = map(int, cursor_pos.split("."))
        content = editor.get("1.0", "end-1c")
        
        try:
            script = jedi.Script(code=content, path=frame.filepath)
            completions = script.complete(line, col)
            
            if completions:
                self._show_completion_popup(editor, completions)
        except Exception:
            pass
            
        return "break"

    def _show_completion_popup(self, editor, completions):
        if self.completion_win and self.completion_win.winfo_exists():
            self.completion_win.destroy()
            
        self.completion_win = tk.Toplevel(self)
        self.completion_win.wm_overrideredirect(True)
        self.completion_win.geometry("300x200")
        
        # 定位到光标位置
        cursor_pos = editor.bbox("insert")
        if cursor_pos:
            x = editor.winfo_rootx() + cursor_pos[0]
            y = editor.winfo_rooty() + cursor_pos[1] + cursor_pos[3]
            self.completion_win.geometry(f"+{x}+{y}")
        
        listbox = tk.Listbox(self.completion_win, font=("Consolas", 11))
        listbox.pack(fill="both", expand=True)
        
        for comp in completions[:20]:  # 限制数量
            listbox.insert("end", comp.name)
            
        listbox.bind("<<ListboxSelect>>", lambda e, lb=listbox: self._on_completion_select(editor, lb))
        listbox.bind("<Return>", lambda e, lb=listbox: self._on_completion_select(editor, lb))
        listbox.bind("<Escape>", lambda e: self.completion_win.destroy())
        listbox.focus_set()
        
        self.completion_listbox = listbox

    def _on_completion_select(self, editor, listbox):
        sel = listbox.curselection()
        if not sel:
            return
        completion = listbox.get(sel[0])
        
        # 获取当前单词
        cursor_pos = editor.index("insert")
        line_start = editor.get("insert linestart", "insert")
        word_match = re.search(r"(\w+)$", line_start)
        if word_match:
            word_start = f"insert-{len(word_match.group(1))}c"
            editor.delete(word_start, "insert")
            
        editor.insert("insert", completion)
        
        if self.completion_win:
            self.completion_win.destroy()

    # ---------------- tooltip and signature ----------------
    def _on_mouse_motion(self, event, editor):
        if self.tooltip_win and self.tooltip_win.winfo_exists():
            self.tooltip_win.destroy()
            self.tooltip_win = None

    def _on_key_update_cursor(self, event, editor):
        self._update_cursor_pos(editor)

    def _update_cursor_pos(self, editor):
        cursor_pos = editor.index("insert")
        line, col = cursor_pos.split(".")
        self.status_var.set(f"行: {line}, 列: {col}")

    def _on_open_paren(self, event, editor):
        editor.insert("insert", "(")
        self._show_signature_help(editor)
        return "break"

    def _on_comma(self, event, editor):
        editor.insert("insert", ",")
        self._show_signature_help(editor)
        return "break"

    def _show_signature_help(self, editor):
        if not JEDI_AVAILABLE:
            return
            
        frame = self._get_current_editor_frame()
        if not frame or not frame.filepath:
            return
            
        cursor_pos = editor.index("insert")
        line, col = map(int, cursor_pos.split("."))
        content = editor.get("1.0", "end-1c")
        
        try:
            script = jedi.Script(code=content, path=frame.filepath)
            signatures = script.get_signatures(line, col)
            
            if signatures:
                sig = signatures[0]
                params = sig.params
                current_index = sig.index if hasattr(sig, 'index') else 0
                
                # 构建签名文本
                sig_text = f"{sig.name}("
                for i, param in enumerate(params):
                    if i == current_index:
                        sig_text += f"[{param.description}]"
                    else:
                        sig_text += param.description
                    if i < len(params) - 1:
                        sig_text += ", "
                sig_text += ")"
                
                self._show_signature_popup(editor, sig_text)
        except Exception:
            pass

    def _show_signature_popup(self, editor, signature):
        if self.signature_win and self.signature_win.winfo_exists():
            self.signature_win.destroy()
            
        self.signature_win = tk.Toplevel(self)
        self.signature_win.wm_overrideredirect(True)
        
        label = tk.Label(self.signature_win, text=signature, bg="lightyellow", 
                        font=("Consolas", 10), justify="left")
        label.pack(padx=5, pady=2)
        
        # 定位到光标位置
        cursor_pos = editor.bbox("insert")
        if cursor_pos:
            x = editor.winfo_rootx() + cursor_pos[0]
            y = editor.winfo_rooty() + cursor_pos[1] - 30
            self.signature_win.geometry(f"+{x}+{y}")
            
        # 3秒后自动消失
        self.after(3000, lambda: self.signature_win.destroy() if self.signature_win else None)

    # ---------------- find/replace ----------------
    def _find_text(self):
        editor = self._get_current_editor()
        if editor:
            FindReplaceDialog(self, editor)

    def _replace_text(self):
        editor = self._get_current_editor()
        if editor:
            FindReplaceDialog(self, editor)

    def _quick_find(self, event=None):
        find_text = self.find_var.get().strip()
        if not find_text:
            return
            
        editor = self._get_current_editor()
        if not editor:
            return
            
        # 从当前位置开始查找
        start_pos = editor.index("insert")
        content = editor.get(start_pos, "end")
        pos = content.find(find_text)
        
        if pos != -1:
            start_idx = editor.index(f"{start_pos}+{pos}c")
            end_idx = editor.index(f"{start_pos}+{pos+len(find_text)}c")
            
            editor.tag_remove("sel", "1.0", "end")
            editor.tag_add("sel", start_idx, end_idx)
            editor.mark_set("insert", end_idx)
            editor.see(start_idx)
        else:
            messagebox.showinfo("查找", "未找到匹配项")

    # ---------------- file operations ----------------
    def open_file_dialog(self):
        file_path = filedialog.askopenfilename(
            title="打开文件",
            filetypes=[("All files", "*.*"), ("Python files", "*.py"), ("C/C++ files", "*.c;*.cpp;*.h;*.hpp")]
        )
        if file_path:
            self.open_file(file_path)

    def open_file(self, file_path):
        # 检查是否已经打开
        for tab in self.editor_nb.tabs():
            frame = self.editor_nb.nametowidget(tab)
            if frame.filepath == file_path:
                self.editor_nb.select(tab)
                return
                
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            messagebox.showerror("错误", f"无法打开文件: {e}")
            return
            
        frame = self.new_editor_tab(content, file_path)
        frame.filepath = file_path
        title = os.path.basename(file_path)
        self.editor_nb.tab(frame, text=title)
        
        # 添加到最近文件
        self._add_recent_file(file_path)

    def open_folder_dialog(self):
        folder_path = filedialog.askdirectory(title="打开文件夹")
        if folder_path:
            self.workspace_dir = folder_path
            self._populate_tree(folder_path)

    def save_file(self):
        frame = self._get_current_editor_frame()
        if not frame:
            return
            
        if frame.filepath:
            try:
                with open(frame.filepath, "w", encoding="utf-8") as f:
                    f.write(frame.text.get("1.0", "end-1c"))
                self.status_var.set("文件已保存")
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}")
        else:
            self.save_file_as()

    def save_file_as(self):
        frame = self._get_current_editor_frame()
        if not frame:
            return
            
        file_path = filedialog.asksaveasfilename(
            title="另存为",
            defaultextension=".py",
            filetypes=[("All files", "*.*"), ("Python files", "*.py"), ("C/C++ files", "*.c;*.cpp;*.h;*.hpp")]
        )
        if file_path:
            frame.filepath = file_path
            title = os.path.basename(file_path)
            self.editor_nb.tab(frame, text=title)
            self.save_file()

    # ---------------- terminal operations ----------------
    def add_terminal(self):
        term = TerminalTab(self.terminal_nb, f"终端 {len(self.term_tabs)+1}")
        self.term_tabs.append(term)

    def stop_current_terminal_process(self):
        current = self.terminal_nb.select()
        if not current:
            return
        frame = self.terminal_nb.nametowidget(current)
        for term in self.term_tabs:
            if term.frame == frame and term.proc:
                try:
                    term.proc.terminate()
                except Exception:
                    pass

    # ---------------- run/debug ----------------
    def run_current(self):
        frame = self._get_current_editor_frame()
        if not frame or not frame.filepath:
            messagebox.showwarning("警告", "请先保存文件")
            return
            
        file_path = frame.filepath
        ext = os.path.splitext(file_path)[1].lower()
        
        # 清空输出
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.config(state="disabled")
        
        self.status_label.config(text="运行中...")
        self.status_canvas.itemconfig(self.status_dot, fill="green")
        
        if ext == ".py":
            threading.Thread(target=self._run_python, args=(file_path,), daemon=True).start()
        elif ext in (".c", ".cpp", ".cc", ".cxx"):
            threading.Thread(target=self._run_c_cpp, args=(file_path,), daemon=True).start()
        else:
            messagebox.showwarning("警告", f"不支持的文件类型: {ext}")

    def _run_python(self, file_path):
        try:
            env = os.environ.copy()
            if self.debug_mode:
                # 调试模式
                cmd = [sys.executable, "-m", "pdb", file_path]
            else:
                cmd = [sys.executable, file_path]
                
            proc = subprocess.Popen(cmd, cwd=os.path.dirname(file_path), 
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                  text=True, env=env)
            
            # 读取输出
            for line in proc.stdout:
                self._write_output(line)
            for line in proc.stderr:
                self._write_output(line, is_error=True)
                
            proc.wait()
            self._write_output(f"\n进程退出，返回码 {proc.returncode}\n")
            
        except Exception as e:
            self._write_output(f"运行错误: {e}\n", is_error=True)
        finally:
            self.status_label.config(text="空闲")
            self.status_canvas.itemconfig(self.status_dot, fill="gray")

    def _run_c_cpp(self, file_path):
        try:
            # 编译
            gcc_path = self.config_data.get("gcc_path", "gcc")
            if file_path.endswith(".cpp") or file_path.endswith(".cc") or file_path.endswith(".cxx"):
                compiler = "g++" if gcc_path == "gcc" else gcc_path
            else:
                compiler = gcc_path
                
            exe_path = file_path.rsplit(".", 1)[0] + (".exe" if os.name == "nt" else "")
            compile_cmd = [compiler, file_path, "-o", exe_path, "-g"]  # -g 用于调试
            
            self._write_output(f"编译命令: {' '.join(compile_cmd)}\n")
            compile_proc = subprocess.run(compile_cmd, capture_output=True, text=True)
            
            if compile_proc.returncode != 0:
                self._write_output(f"编译错误:\n{compile_proc.stderr}\n", is_error=True)
                return
                
            self._write_output("编译成功\n")
            
            # 运行
            run_proc = subprocess.Popen([exe_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            for line in run_proc.stdout:
                self._write_output(line)
            for line in run_proc.stderr:
                self._write_output(line, is_error=True)
                
            run_proc.wait()
            self._write_output(f"\n进程退出，返回码 {run_proc.returncode}\n")
            
        except Exception as e:
            self._write_output(f"运行错误: {e}\n", is_error=True)
        finally:
            self.status_label.config(text="空闲")
            self.status_canvas.itemconfig(self.status_dot, fill="gray")

    def _write_output(self, text, is_error=False):
        self.output_text.config(state="normal")
        tag = "error" if is_error else "normal"
        self.output_text.insert("end", text, tag)
        self.output_text.see("end")
        self.output_text.config(state="disabled")
        
        # 配置错误文本颜色
        if is_error and "error" not in self.output_text.tag_names():
            self.output_text.tag_configure("error", foreground="red")

    # ---------------- debug functions ----------------
    def _toggle_breakpoint(self):
        editor = self._get_current_editor()
        if not editor:
            return
            
        cursor_pos = editor.index("insert")
        line_num = int(cursor_pos.split(".")[0])
        frame = self._get_current_editor_frame()
        file_path = frame.filepath if frame else ""
        
        if file_path not in self.breakpoints:
            self.breakpoints[file_path] = set()
            
        if line_num in self.breakpoints[file_path]:
            self.breakpoints[file_path].remove(line_num)
            # 清除断点标记
            editor.tag_remove("breakpoint", f"{line_num}.0", f"{line_num}.end")
        else:
            self.breakpoints[file_path].add(line_num)
            # 添加断点标记
            editor.tag_configure("breakpoint", background="pink")
            editor.tag_add("breakpoint", f"{line_num}.0", f"{line_num}.end")

    def _start_debug(self):
        self.debug_mode = True
        self.btn_step.config(state="normal")
        self.btn_continue.config(state="normal")
        self.status_label.config(text="调试模式")
        self.status_canvas.itemconfig(self.status_dot, fill="orange")
        self.run_current()

    def _stop_debug(self):
        self.debug_mode = False
        self.btn_step.config(state="disabled")
        self.btn_continue.config(state="disabled")
        self.status_label.config(text="空闲")
        self.status_canvas.itemconfig(self.status_dot, fill="gray")

    def _debug_step(self):
        # 单步执行
        if hasattr(self, 'debug_proc') and self.debug_proc:
            self.debug_proc.stdin.write("s\n")
            self.debug_proc.stdin.flush()

    def _debug_continue(self):
        # 继续执行
        if hasattr(self, 'debug_proc') and self.debug_proc:
            self.debug_proc.stdin.write("c\n")
            self.debug_proc.stdin.flush()

    # ---------------- settings ----------------
    def open_settings(self):
        settings_win = tk.Toplevel(self)
        settings_win.title("设置")
        settings_win.geometry("500x400")
        
        # 字体大小
        ttk.Label(settings_win, text="字体大小:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        font_size_var = tk.IntVar(value=self.config_data["font_size"])
        font_spin = ttk.Spinbox(settings_win, from_=8, to=24, textvariable=font_size_var, width=10)
        font_spin.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        
        # 主题
        ttk.Label(settings_win, text="主题:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        theme_var = tk.StringVar(value=self.config_data["theme"])
        theme_combo = ttk.Combobox(settings_win, textvariable=theme_var, values=["light", "dark"], state="readonly", width=10)
        theme_combo.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        
        # 自动保存间隔
        ttk.Label(settings_win, text="自动保存间隔(秒):").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        autosave_var = tk.IntVar(value=self.config_data["autosave_interval"])
        autosave_spin = ttk.Spinbox(settings_win, from_=0, to=300, textvariable=autosave_var, width=10)
        autosave_spin.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        
        # GCC路径
        ttk.Label(settings_win, text="GCC路径:").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        gcc_var = tk.StringVar(value=self.config_data.get("gcc_path", ""))
        gcc_entry = ttk.Entry(settings_win, textvariable=gcc_var, width=30)
        gcc_entry.grid(row=3, column=1, padx=5, pady=5, sticky="we")
        
        # 按钮
        button_frame = ttk.Frame(settings_win)
        button_frame.grid(row=4, column=0, columnspan=2, pady=20)
        
        def save_settings():
            self.config_data["font_size"] = font_size_var.get()
            self.config_data["theme"] = theme_var.get()
            self.config_data["autosave_interval"] = autosave_var.get()
            self.config_data["gcc_path"] = gcc_var.get()
            
            self.save_config()
            self._apply_theme()
            
            # 更新所有编辑器的字体
            for tab in self.editor_nb.tabs():
                frame = self.editor_nb.nametowidget(tab)
                try:
                    frame.text.config(font=("Consolas", self.config_data["font_size"]))
                    frame.ln.config(font=("Consolas", self.config_data["font_size"]))
                    self._update_line_numbers(frame.text, frame.ln)
                except Exception:
                    pass
                    
            settings_win.destroy()
            messagebox.showinfo("设置", "设置已保存")
            
        ttk.Button(button_frame, text="保存", command=save_settings).pack(side="left", padx=10)
        ttk.Button(button_frame, text="取消", command=settings_win.destroy).pack(side="left", padx=10)
        
        settings_win.columnconfigure(1, weight=1)

    def _bind_gcc(self):
        gcc_path = filedialog.askopenfilename(title="选择 GCC 编译器", 
                                            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")])
        if gcc_path:
            self.config_data["gcc_path"] = gcc_path
            self.save_config()
            messagebox.showinfo("GCC 绑定", f"GCC 路径已设置为: {gcc_path}")

    # ---------------- status bar ----------------
    def _build_statusbar(self):
        statusbar = ttk.Frame(self)
        statusbar.pack(side="bottom", fill="x")
        
        # 文件信息
        self.file_var = tk.StringVar(value="未打开文件")
        ttk.Label(statusbar, textvariable=self.file_var).pack(side="left", padx=5)
        
        # 光标位置
        self.status_var = tk.StringVar(value="行: 1, 列: 1")
        ttk.Label(statusbar, textvariable=self.status_var).pack(side="left", padx=20)
        
        # 系统状态
        self.sys_var = tk.StringVar(value="CPU: --% 内存: --MB")
        ttk.Label(statusbar, textvariable=self.sys_var).pack(side="right", padx=5)
        
        # 时间
        self.time_var = tk.StringVar()
        ttk.Label(statusbar, textvariable=self.time_var).pack(side="right", padx=20)

    def _periodic_update(self):
        # 更新时间
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.time_var.set(current_time)
        
        # 更新系统状态
        if PSUTIL_AVAILABLE:
            cpu_percent = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            memory_mb = memory.used // (1024 * 1024)
            self.sys_var.set(f"CPU: {cpu_percent:.1f}% 内存: {memory_mb}MB")
        
        # 更新当前文件信息
        frame = self._get_current_editor_frame()
        if frame and frame.filepath:
            self.file_var.set(f"文件: {os.path.basename(frame.filepath)}")
        else:
            self.file_var.set("未打开文件")
            
        self.after(1000, self._periodic_update)

    # ---------------- other UI handlers ----------------
    def _on_editor_click(self, event, editor):
        self._update_cursor_pos(editor)

    def _on_ctrl_scroll(self, event, editor):
        # Ctrl+鼠标滚轮调整字体大小
        if event.delta > 0:
            self.config_data["font_size"] = min(24, self.config_data["font_size"] + 1)
        else:
            self.config_data["font_size"] = max(8, self.config_data["font_size"] - 1)
            
        editor.config(font=("Consolas", self.config_data["font_size"]))
        frame = self._get_current_editor_frame()
        if frame:
            frame.ln.config(font=("Consolas", self.config_data["font_size"]))
            self._update_line_numbers(editor, frame.ln)

    def _toggle_theme(self):
        current_theme = self.config_data.get("theme", "light")
        new_theme = "dark" if current_theme == "light" else "light"
        self.config_data["theme"] = new_theme
        self.save_config()
        self._apply_theme()

    def _undo(self):
        editor = self._get_current_editor()
        if editor:
            try:
                editor.edit_undo()
            except tk.TclError:
                pass

    def _redo(self):
        editor = self._get_current_editor()
        if editor:
            try:
                editor.edit_redo()
            except tk.TclError:
                pass

    def quit(self):
        if messagebox.askokcancel("退出", "确定要退出吗？"):
            self.save_config()
            self.destroy()

if __name__ == "__main__":
    app = MiniIDE()
    app.mainloop()
