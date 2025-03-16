import os
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import win32api
import win32file
import win32con
import pywintypes
import logging
import ctypes
import sys
import threading

# ==================== 管理员权限检查 ====================
def require_admin():
    try:
        if ctypes.windll.shell32.IsUserAnAdmin() == 0:
            cwd = os.getcwd()
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, f'"{sys.argv[0]}"', cwd, 0)
            sys.exit()
    except Exception as e:
        messagebox.showerror("权限错误", f"需要管理员权限运行: {str(e)}")
        sys.exit(1)

require_admin()

# ==================== 资源路径处理 ====================
def resource_path(relative_path):
    search_paths = [
        getattr(sys, '_MEIPASS', os.path.abspath(".")),
        os.path.abspath("."),
        os.path.dirname(sys.argv[0]),
        os.path.join(os.getcwd(), "resources")
    ]
    
    for base_path in search_paths:
        full_path = os.path.join(base_path, relative_path)
        if os.path.exists(full_path):
            return full_path
    
    logging.warning(f"资源文件未找到: {relative_path}")
    return None

# ==================== 日志配置 ====================
logging.basicConfig(
    filename=os.path.join(os.getcwd(), 'FileTimeEditor.log'),
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='w'
)

class DirectoryBrowser(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("选择目录")
        self.geometry("800x600")
        self.selected_path = None
        self.history = []
        self.history_index = -1

        # 加载系统图标
        self._load_icons()
        
        # 创建工具栏
        self.toolbar = ttk.Frame(self)
        self.toolbar.pack(fill='x', padx=5, pady=5)
        
        # 导航按钮
        self.back_btn = ttk.Button(self.toolbar, text="←", command=self.go_back, state='disabled')
        self.back_btn.pack(side='left')
        self.forward_btn = ttk.Button(self.toolbar, text="→", command=self.go_forward, state='disabled')
        self.forward_btn.pack(side='left', padx=5)
        
        # 地址栏
        self.path_var = tk.StringVar()
        self.address_box = ttk.Combobox(
            self.toolbar, 
            textvariable=self.path_var,
            width=50,
            state='readonly'
        )
        self.address_box.pack(side='left', fill='x', expand=True, padx=5)
        self.address_box.bind("<<ComboboxSelected>>", self.on_path_select)
        
        # 刷新按钮
        self.refresh_btn = ttk.Button(self.toolbar, text="↻", command=self.refresh)
        self.refresh_btn.pack(side='left')
        
        # 文件树状视图
        self.tree = ttk.Treeview(
            self,
            columns=("type", "size", "modified"),
            show='tree headings',
            selectmode='browse'
        )
        self._configure_columns()
        
        # 滚动条
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        # 布局
        self.tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')
        
        # 事件绑定
        self.tree.bind("<Double-1>", self.on_double_click)
        self.path_var.trace_add('write', self.on_path_changed)
        
        # 初始化加载
        self.load_drives()

    def _load_icons(self):
        """加载系统图标"""
        try:
            icon_path = resource_path('folder.ico')
            self.folder_icon = tk.PhotoImage(file=icon_path)
            self.file_icon = tk.PhotoImage(file=resource_path('file.ico'))
        except Exception as e:
            logging.error(f"图标加载失败: {str(e)}")
            self.folder_icon = ""
            self.file_icon = ""

    def _configure_columns(self):
        """配置树状视图列"""
        self.tree.heading("#0", text="名称", anchor='w')
        self.tree.heading("type", text="类型")
        self.tree.heading("size", text="大小")
        self.tree.heading("modified", text="修改日期")
        
        self.tree.column("#0", width=300, anchor='w')
        self.tree.column("type", width=120)
        self.tree.column("size", width=100)
        self.tree.column("modified", width=150)

    def load_drives(self):
        """加载所有可用磁盘"""
        self._show_loading()
        threading.Thread(target=self._load_drives_thread, daemon=True).start()

    def _load_drives_thread(self):
        """后台加载磁盘列表"""
        try:
            drives = win32api.GetLogicalDriveStrings().split('\x00')[:-1]
            valid_drives = [d for d in drives if win32api.GetDriveType(d) in (2, 3, 4, 5)]
            self.after(0, self._update_drive_list, valid_drives)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("错误", f"无法加载磁盘列表: {str(e)}"))

    def _update_drive_list(self, drives):
        """更新磁盘列表显示"""
        self.tree.delete(*self.tree.get_children())
        for drive in drives:
            self.tree.insert("", "end", 
                           text=f"本地磁盘 ({drive[:-1]})",
                           values=("磁盘驱动器", "", ""),
                           image=self.folder_icon,
                           tags=(drive,))
        self.update_address_box(drives=drives)
        if drives:
            self.path_var.set(drives[0])

    def update_address_box(self, paths=None, drives=None):
        """更新地址栏下拉列表"""
        if drives:
            display_drives = [f"本地磁盘 ({d[:-1]})" for d in drives]
            self.address_box['values'] = display_drives
        elif paths:
            self.address_box['values'] = paths

    def on_path_select(self, event):
        """处理地址栏选择事件"""
        selected = self.address_box.get()
        if selected.startswith("本地磁盘"):
            drive = selected[-3] + ":\\"
            self.navigate_to(drive)

    def navigate_to(self, path):
        """导航到指定路径"""
        if not os.path.exists(path):
            messagebox.showerror("错误", "路径不存在")
            return
        
        self._show_loading()
        threading.Thread(target=self._load_directory_thread, args=(path,), daemon=True).start()

    def _load_directory_thread(self, path):
        """后台加载目录内容"""
        try:
            items = os.listdir(path)
            dirs = []
            files = []
            
            for item in items:
                full_path = os.path.join(path, item)
                if os.path.isdir(full_path):
                    dirs.append((item, full_path))
                else:
                    files.append((item, full_path))
            
            self.after(0, self._update_directory_view, path, dirs, files)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("错误", f"无法访问路径: {str(e)}"))

    def _update_directory_view(self, path, dirs, files):
        """更新目录视图"""
        self.tree.delete(*self.tree.get_children())
        
        # 添加返回上级目录
        parent_path = os.path.dirname(path)
        if os.path.normpath(path) != os.path.normpath(parent_path):
            self.tree.insert("", "end",
                           text="..",
                           values=("上级目录", "", ""),
                           image=self.folder_icon,
                           tags=(parent_path,))
        
        # 添加子目录
        for name, full_path in dirs:
            self.tree.insert("", "end",
                           text=name,
                           values=("文件夹", "", ""),
                           image=self.folder_icon,
                           tags=(full_path,))
        
        # 添加文件
        for name, full_path in files:
            size = os.path.getsize(full_path)
            mtime = datetime.fromtimestamp(os.path.getmtime(full_path)).strftime('%Y-%m-%d %H:%M:%S')
            self.tree.insert("", "end",
                           text=name,
                           values=("文件", self.format_size(size), mtime),
                           image=self.file_icon,
                           tags=(full_path,))
        
        # 更新历史记录
        self._update_history(path)
        self.path_var.set(path)
        self.update_navigation_buttons()

    def _update_history(self, path):
        """更新导航历史记录"""
        if self.history and self.history_index >= 0:
            if self.history[self.history_index] == path:
                return
        self.history = self.history[:self.history_index+1]
        self.history.append(path)
        self.history_index = len(self.history) - 1

    def update_navigation_buttons(self):
        """更新导航按钮状态"""
        self.back_btn.config(state='normal' if self.history_index > 0 else 'disabled')
        self.forward_btn.config(state='normal' if self.history_index < len(self.history)-1 else 'disabled')

    def go_back(self):
        """后退导航"""
        if self.history_index > 0:
            self.history_index -= 1
            self.navigate_to(self.history[self.history_index])

    def go_forward(self):
        """前进导航"""
        if self.history_index < len(self.history)-1:
            self.history_index += 1
            self.navigate_to(self.history[self.history_index])

    def on_double_click(self, event):
        """处理双击事件"""
        item = self.tree.selection()[0]
        path = self.tree.item(item, "tags")[0]
        if os.path.isdir(path):
            self.navigate_to(path)

    def on_path_changed(self, *args):
        """路径输入变化处理"""
        path = self.path_var.get()
        if os.path.exists(path):
            self.navigate_to(path)

    def refresh(self):
        """刷新当前目录"""
        current_path = self.path_var.get()
        if current_path:
            self.navigate_to(current_path)

    def format_size(self, size):
        """格式化文件大小显示"""
        try:
            for unit in ['B','KB','MB','GB']:
                if size < 1024.0:
                    return f"{size:.1f} {unit}"
                size /= 1024.0
            return f"{size:.1f} TB"
        except:
            return "N/A"

    def _show_loading(self):
        """显示加载状态"""
        self.tree.delete(*self.tree.get_children())
        self.tree.insert("", "end", text="加载中...", values=("", "", ""))

class FileTimeEditor:
    def __init__(self, root):
        self.root = root
        self.setup_ui()

    def setup_ui(self):
        self.root.title("文件时间修改工具 2.0")
        self.root.geometry("1000x600")
        self.load_application_icon()
        self.setup_menu()
        self.selected_path = self.show_directory_browser()
        self.setup_main_interface()

    def load_application_icon(self):
        icon_path = resource_path('nft2.0.ico')
        if icon_path and os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception as e:
                logging.error(f"图标加载失败: {str(e)}")

    def setup_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="打开目录", command=self.reopen_directory_browser)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.destroy)
        menubar.add_cascade(label="文件", menu=file_menu)
        self.root.config(menu=menubar)

    def show_directory_browser(self):
        browser = DirectoryBrowser(self.root)
        self.root.wait_window(browser)
        return browser.selected_path or os.getcwd()

    def setup_main_interface(self):
        self.tree = ttk.Treeview(self.root, columns=("文件名", "创建日期", "修改日期"), show="headings")
        for col in ("文件名", "创建日期", "修改日期"):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150)
        
        vsb = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        
        self.status_label = tk.Label(self.root, text=f"当前目录: {self.selected_path}", anchor='w')
        self.status_label.pack(fill='x')
        self.populate_file_list()

    def populate_file_list(self):
        self.tree.delete(*self.tree.get_children())
        try:
            for item in os.listdir(self.selected_path):
                path = os.path.join(self.selected_path, item)
                if os.path.isfile(path):
                    ctime = datetime.fromtimestamp(os.path.getctime(path)).strftime('%Y-%m-%d %H:%M:%S')
                    mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M:%S')
                    self.tree.insert("", "end", values=(item, ctime, mtime))
        except Exception as e:
            messagebox.showerror("错误", f"无法加载文件列表: {str(e)}")

    def reopen_directory_browser(self):
        new_path = self.show_directory_browser()
        if new_path != self.selected_path:
            self.selected_path = new_path
            self.status_label.config(text=f"当前目录: {self.selected_path}")
            self.populate_file_list()

if __name__ == "__main__":
    root = tk.Tk()
    app = FileTimeEditor(root)
    root.mainloop()
